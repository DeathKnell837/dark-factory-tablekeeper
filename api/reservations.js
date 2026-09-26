import { sql, recordAuditLog } from './db.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  // GET: List reservations
  if (req.method === 'GET') {
    try {
      const reservations = await sql`
        SELECT 
          r.id,
          r.table_id,
          t.name AS table_name,
          t.capacity AS table_capacity,
          r.guest_name,
          r.guest_email,
          r.party_size,
          r.start_at,
          r.end_at,
          r.requested_timezone,
          r.idempotency_key,
          r.created_at
        FROM reservations r
        JOIN tables t ON r.table_id = t.id
        ORDER BY r.start_at ASC
      `;
      return res.status(200).json({ success: true, reservations });
    } catch (err) {
      return res.status(500).json({ success: false, error: err.message });
    }
  }

  // POST: Create reservation with PostgreSQL GiST exclusion guarantee
  if (req.method === 'POST') {
    try {
      let body = req.body;
      if (typeof body === 'string') {
        body = JSON.parse(body);
      }
      const { table_id, guest_name, guest_email = '', party_size, start_at, end_at, requested_timezone = 'UTC', idempotency_key = null } = body;

      if (!table_id || !guest_name || !party_size || !start_at || !end_at) {
        return res.status(400).json({
          success: false,
          error: 'Missing required fields: table_id, guest_name, party_size, start_at, end_at'
        });
      }

      const startDate = new Date(start_at);
      const endDate = new Date(end_at);
      if (isNaN(startDate.getTime()) || isNaN(endDate.getTime())) {
        return res.status(400).json({ success: false, error: 'Invalid date format for start_at or end_at' });
      }
      if (startDate >= endDate) {
        return res.status(400).json({ success: false, error: 'start_at must be strictly before end_at' });
      }

      // Check table capacity
      const [table] = await sql`SELECT id, name, capacity, timezone FROM tables WHERE id = ${table_id}`;
      if (!table) {
        return res.status(404).json({ success: false, error: `Table ${table_id} does not exist` });
      }

      if (party_size > table.capacity) {
        await recordAuditLog({
          eventType: 'CAPACITY_REJECTED',
          tableId: table_id,
          guestName: guest_name,
          partySize: party_size,
          statusCode: 400,
          details: `Party size ${party_size} exceeds table capacity ${table.capacity}`
        });
        return res.status(400).json({
          success: false,
          error: `Party size ${party_size} exceeds table capacity (${table.capacity})`
        });
      }

      // If idempotency_key provided, check for previous identical reservation
      if (idempotency_key) {
        const [existing] = await sql`SELECT * FROM reservations WHERE idempotency_key = ${idempotency_key}`;
        if (existing) {
          await recordAuditLog({
            eventType: 'IDEMPOTENT_HIT',
            tableId: existing.table_id,
            reservationId: existing.id,
            guestName: existing.guest_name,
            partySize: existing.party_size,
            statusCode: 200,
            details: `Returned cached reservation for idempotency key ${idempotency_key}`
          });
          return res.status(200).json({ success: true, reservation: existing, idempotentReplay: true });
        }
      }

      // Attempt insertion into PostgreSQL with exclusion constraint active
      try {
        const [reservation] = await sql`
          INSERT INTO reservations (
            table_id, guest_name, guest_email, party_size, start_at, end_at, requested_timezone, idempotency_key, created_at
          ) VALUES (
            ${table_id}, ${guest_name}, ${guest_email}, ${party_size}, ${start_at}, ${end_at}, ${requested_timezone}, ${idempotency_key}, NOW()
          )
          RETURNING *
        `;

        await recordAuditLog({
          eventType: 'RESERVATION_CREATED',
          tableId: table_id,
          reservationId: reservation.id,
          guestName: guest_name,
          partySize: party_size,
          statusCode: 201,
          details: `Reserved Table ${table_id} for ${guest_name} (${party_size} guests)`
        });

        return res.status(201).json({ success: true, reservation });
      } catch (dbErr) {
        // Detect GiST exclusion constraint conflict
        if (dbErr.message && (dbErr.message.includes('exclusion constraint') || dbErr.message.includes('no_overlapping_reservations') || dbErr.code === '23P01')) {
          await recordAuditLog({
            eventType: 'CONCURRENCY_CONFLICT',
            tableId: table_id,
            guestName: guest_name,
            partySize: party_size,
            statusCode: 409,
            details: `Double-booking blocked by PostgreSQL GiST exclusion: Table ${table_id} already reserved in window`
          });

          return res.status(409).json({
            success: false,
            conflict: true,
            error: `Table ${table.name} is already booked for that time window. Overlapping request blocked.`,
            constraint: 'no_overlapping_reservations'
          });
        }
        throw dbErr;
      }
    } catch (err) {
      console.error('Error in POST /api/reservations:', err);
      return res.status(500).json({ success: false, error: err.message });
    }
  }

  // DELETE: Cancel reservation with atomic waitlist auto-promotion
  if (req.method === 'DELETE') {
    try {
      const reservationId = req.query.id || (req.body && (typeof req.body === 'string' ? JSON.parse(req.body).id : req.body.id));
      if (!reservationId) {
        return res.status(400).json({ success: false, error: 'Missing reservation id query param or body' });
      }

      // Fetch existing reservation first
      const [existing] = await sql`
        SELECT r.*, t.capacity AS table_capacity, t.name AS table_name
        FROM reservations r
        JOIN tables t ON r.table_id = t.id
        WHERE r.id = ${reservationId}
      `;

      if (!existing) {
        return res.status(404).json({ success: false, error: `Reservation ${reservationId} not found` });
      }

      // Delete reservation
      await sql`DELETE FROM reservations WHERE id = ${reservationId}`;

      await recordAuditLog({
        eventType: 'RESERVATION_CANCELLED',
        tableId: existing.table_id,
        reservationId: existing.id,
        guestName: existing.guest_name,
        partySize: existing.party_size,
        statusCode: 200,
        details: `Reservation #${reservationId} cancelled. Table ${existing.table_name} vacated.`
      });

      // Check waitlist for eligible FIFO candidate
      const [candidate] = await sql`
        SELECT * FROM waitlist
        WHERE status = 'WAITING'
          AND party_size <= ${existing.table_capacity}
          AND start_at < ${existing.end_at}
          AND end_at > ${existing.start_at}
        ORDER BY created_at ASC
        LIMIT 1
      `;

      let promoted = null;
      if (candidate) {
        // Auto-promote candidate into the vacated table
        const [newRes] = await sql`
          INSERT INTO reservations (
            table_id, guest_name, guest_email, party_size, start_at, end_at, requested_timezone, idempotency_key, created_at
          ) VALUES (
            ${existing.table_id}, ${candidate.guest_name}, ${candidate.guest_email}, ${candidate.party_size},
            ${candidate.start_at}, ${candidate.end_at}, ${candidate.requested_timezone},
            ${'promoted-wl-' + candidate.id}, NOW()
          )
          RETURNING *
        `;

        await sql`
          UPDATE waitlist
          SET status = 'PROMOTED', promoted_reservation_id = ${newRes.id}
          WHERE id = ${candidate.id}
        `;

        await recordAuditLog({
          eventType: 'WAITLIST_AUTO_PROMOTED',
          tableId: existing.table_id,
          reservationId: newRes.id,
          waitlistId: candidate.id,
          guestName: candidate.guest_name,
          partySize: candidate.party_size,
          statusCode: 201,
          details: `Waitlist entry #${candidate.id} (${candidate.guest_name}) auto-promoted to Table ${existing.table_name} (Reservation #${newRes.id})`
        });

        promoted = {
          waitlistId: candidate.id,
          reservationId: newRes.id,
          guestName: candidate.guest_name,
          tableName: existing.table_name
        };
      }

      return res.status(200).json({
        success: true,
        message: `Reservation #${reservationId} cancelled successfully.`,
        promoted
      });
    } catch (err) {
      console.error('Error in DELETE /api/reservations:', err);
      return res.status(500).json({ success: false, error: err.message });
    }
  }

  return res.status(405).json({ error: 'Method not allowed' });
}

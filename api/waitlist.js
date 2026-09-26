import { sql, recordAuditLog } from './db.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  // GET: List waitlist
  if (req.method === 'GET') {
    try {
      const waitlist = await sql`
        SELECT 
          id,
          guest_name,
          guest_email,
          party_size,
          start_at,
          end_at,
          requested_timezone,
          status,
          promoted_reservation_id,
          created_at
        FROM waitlist
        ORDER BY created_at ASC
      `;
      return res.status(200).json({ success: true, waitlist });
    } catch (err) {
      return res.status(500).json({ success: false, error: err.message });
    }
  }

  // POST: Join waitlist
  if (req.method === 'POST') {
    try {
      let body = req.body;
      if (typeof body === 'string') {
        body = JSON.parse(body);
      }
      const { guest_name, guest_email = '', party_size, start_at, end_at, requested_timezone = 'UTC' } = body;

      if (!guest_name || !party_size || !start_at || !end_at) {
        return res.status(400).json({
          success: false,
          error: 'Missing required fields: guest_name, party_size, start_at, end_at'
        });
      }

      const [entry] = await sql`
        INSERT INTO waitlist (
          guest_name, guest_email, party_size, start_at, end_at, requested_timezone, status, created_at
        ) VALUES (
          ${guest_name}, ${guest_email}, ${party_size}, ${start_at}, ${end_at}, ${requested_timezone}, 'WAITING', NOW()
        )
        RETURNING *
      `;

      await recordAuditLog({
        eventType: 'WAITLIST_JOINED',
        waitlistId: entry.id,
        guestName: guest_name,
        partySize: party_size,
        statusCode: 201,
        details: `Guest ${guest_name} (party of ${party_size}) added to FIFO waitlist queue (#${entry.id})`
      });

      return res.status(201).json({ success: true, entry });
    } catch (err) {
      console.error('Error in POST /api/waitlist:', err);
      return res.status(500).json({ success: false, error: err.message });
    }
  }

  // DELETE: Remove from waitlist
  if (req.method === 'DELETE') {
    try {
      const waitlistId = req.query.id || (req.body && (typeof req.body === 'string' ? JSON.parse(req.body).id : req.body.id));
      if (!waitlistId) {
        return res.status(400).json({ success: false, error: 'Missing waitlist id' });
      }

      const [deleted] = await sql`
        DELETE FROM waitlist WHERE id = ${waitlistId} RETURNING *
      `;

      if (!deleted) {
        return res.status(404).json({ success: false, error: `Waitlist entry ${waitlistId} not found` });
      }

      await recordAuditLog({
        eventType: 'WAITLIST_REMOVED',
        waitlistId: deleted.id,
        guestName: deleted.guest_name,
        partySize: deleted.party_size,
        statusCode: 200,
        details: `Waitlist entry #${waitlistId} removed`
      });

      return res.status(200).json({ success: true, message: `Waitlist entry #${waitlistId} removed` });
    } catch (err) {
      return res.status(500).json({ success: false, error: err.message });
    }
  }

  return res.status(405).json({ error: 'Method not allowed' });
}

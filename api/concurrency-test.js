import { sql, recordAuditLog } from './db.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    let body = req.body || {};
    if (typeof body === 'string') {
      body = JSON.parse(body);
    }

    const tableId = parseInt(body.table_id || 1, 10);
    const count = Math.min(Math.max(parseInt(body.count || 50, 10), 5), 50); // Safe bounds: 5 to 50
    const partySize = parseInt(body.party_size || 2, 10);

    // 1. Clean up prior automated stress-test artifacts on this table so every run evaluates a fresh race condition
    await sql`DELETE FROM reservations WHERE idempotency_key LIKE 'stress-%'`;

    // 2. Select a guaranteed open 2-hour window on this table, after any manual reservations
    const existing = await sql`
      SELECT end_at FROM reservations 
      WHERE table_id = ${tableId} 
      ORDER BY end_at DESC 
      LIMIT 1
    `;

    let baseEpoch = Date.now() + 86400000; // +24h default
    if (existing.length > 0 && existing[0].end_at) {
      const maxEnd = new Date(existing[0].end_at).getTime();
      if (maxEnd >= baseEpoch) {
        baseEpoch = maxEnd + 3600000; // +1h after last user booking
      }
    }

    const startTimeIso = new Date(baseEpoch).toISOString();
    const endTimeIso = new Date(baseEpoch + 7200000).toISOString();

    const nowEpoch = Date.now();
    const overallStart = Date.now();

    // 3. Spawn 50 simultaneous parallel asynchronous promises against Neon PostgreSQL
    const promises = Array.from({ length: count }, async (_, i) => {
      const guestName = `StressRunner-${i + 1}-${nowEpoch.toString().slice(-4)}`;
      const reqStart = Date.now();

      try {
        const [reservation] = await sql`
          INSERT INTO reservations (
            table_id, guest_name, guest_email, party_size, start_at, end_at, requested_timezone, idempotency_key, created_at
          ) VALUES (
            ${tableId}, ${guestName}, ${guestName.toLowerCase() + '@stress.internal'}, ${partySize},
            ${startTimeIso}, ${endTimeIso}, 'UTC', ${'stress-' + nowEpoch + '-' + i}, NOW()
          )
          RETURNING id, guest_name, party_size, start_at, end_at, created_at
        `;

        const latency = Date.now() - reqStart;
        return {
          index: i + 1,
          guestName,
          status: 201,
          statusText: '201 CREATED',
          reservationId: reservation.id,
          latencyMs: latency,
          error: null
        };
      } catch (err) {
        const latency = Date.now() - reqStart;
        const isConflict = err.message && (
          err.message.includes('exclusion constraint') || 
          err.message.includes('no_overlapping_reservations') ||
          err.code === '23P01'
        );

        return {
          index: i + 1,
          guestName,
          status: isConflict ? 409 : 500,
          statusText: isConflict ? '409 CONFLICT' : '500 ERROR',
          reservationId: null,
          latencyMs: latency,
          error: isConflict 
            ? 'PostgreSQL GiST exclusion violation: zero double-booking kernel guarantee' 
            : err.message
        };
      }
    });

    const results = await Promise.all(promises);
    const overallDuration = Date.now() - overallStart;

    const successes = results.filter(r => r.status === 201);
    const conflicts = results.filter(r => r.status === 409);
    const errors = results.filter(r => r.status !== 201 && r.status !== 409);

    // Record summarized audit log
    await recordAuditLog({
      eventType: 'STRESS_TEST_BURST',
      tableId,
      reservationId: successes[0]?.reservationId || null,
      statusCode: successes.length === 1 ? 200 : 500,
      details: `Executed ${count} real parallel DB queries: ${successes.length} created (201), ${conflicts.length} blocked (409) in ${overallDuration}ms.`
    });

    return res.status(200).json({
      success: true,
      meta: {
        engine: 'Neon Serverless PostgreSQL 16 + GiST Exclusion Constraints',
        tableId,
        totalRequests: count,
        successCount: successes.length,
        conflictCount: conflicts.length,
        errorCount: errors.length,
        totalDurationMs: overallDuration,
        averageLatencyMs: Math.round(results.reduce((acc, r) => acc + r.latencyMs, 0) / count)
      },
      winner: successes[0] || null,
      results
    });
  } catch (err) {
    console.error('Error in POST /api/concurrency-test:', err);
    return res.status(500).json({ success: false, error: err.message });
  }
}

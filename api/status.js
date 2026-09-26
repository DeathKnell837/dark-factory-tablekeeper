import { sql } from './db.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  const start = Date.now();
  try {
    const [counts] = await sql`
      SELECT 
        (SELECT COUNT(*) FROM tables)::int AS tables_count,
        (SELECT COUNT(*) FROM reservations)::int AS reservations_count,
        (SELECT COUNT(*) FROM waitlist WHERE status = 'WAITING')::int AS waitlist_waiting_count,
        (SELECT COUNT(*) FROM audit_logs)::int AS audit_logs_count,
        NOW() AS server_time
    `;
    const latencyMs = Date.now() - start;

    return res.status(200).json({
      status: 'operational',
      database: 'Neon Serverless PostgreSQL 16 (AWS us-east-1)',
      concurrencyEngine: 'PostgreSQL GiST Exclusion Constraints',
      latencyMs,
      data: counts
    });
  } catch (err) {
    return res.status(500).json({
      status: 'error',
      error: err.message
    });
  }
}

import { sql } from './db.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    const limit = Math.min(parseInt(req.query.limit || 50, 10), 100);
    const logs = await sql`
      SELECT 
        a.id,
        a.event_type,
        a.table_id,
        t.name AS table_name,
        a.reservation_id,
        a.waitlist_id,
        a.guest_name,
        a.party_size,
        a.status_code,
        a.details,
        a.created_at
      FROM audit_logs a
      LEFT JOIN tables t ON a.table_id = t.id
      ORDER BY a.created_at DESC, a.id DESC
      LIMIT ${limit}
    `;

    return res.status(200).json({ success: true, logs });
  } catch (err) {
    return res.status(500).json({ success: false, error: err.message });
  }
}

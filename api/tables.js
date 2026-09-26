import { sql } from './db.js';

export default async function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  try {
    const tables = await sql`
      SELECT 
        t.id,
        t.name,
        t.capacity,
        t.timezone,
        COALESCE(
          json_agg(
            json_build_object(
              'id', r.id,
              'guest_name', r.guest_name,
              'party_size', r.party_size,
              'start_at', r.start_at,
              'end_at', r.end_at,
              'requested_timezone', r.requested_timezone
            ) ORDER BY r.start_at ASC
          ) FILTER (WHERE r.id IS NOT NULL),
          '[]'::json
        ) AS current_reservations
      FROM tables t
      LEFT JOIN reservations r ON t.id = r.table_id
      GROUP BY t.id, t.name, t.capacity, t.timezone
      ORDER BY t.id ASC
    `;

    return res.status(200).json({
      success: true,
      tables
    });
  } catch (err) {
    return res.status(500).json({
      success: false,
      error: err.message
    });
  }
}

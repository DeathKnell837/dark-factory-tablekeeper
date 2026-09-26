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
    await sql`DELETE FROM reservations`;
    await sql`DELETE FROM waitlist`;
    await sql`DELETE FROM audit_logs`;

    await recordAuditLog({
      eventType: 'SYSTEM_INITIALIZED',
      statusCode: 200,
      details: 'Demonstration environment reset to clean factory state.'
    });

    return res.status(200).json({
      success: true,
      message: 'Database reset to clean factory state. Tables preserved, reservations, waitlist, and logs cleared.'
    });
  } catch (err) {
    return res.status(500).json({ success: false, error: err.message });
  }
}

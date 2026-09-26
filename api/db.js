import { neon } from '@neondatabase/serverless';

const connectionString = process.env.DATABASE_URL || 'postgresql://neondb_owner:npg_MrCTUSv60LyZ@ep-hidden-morning-avzotqz1-pooler.c-11.us-east-1.aws.neon.tech/tablekeeper?sslmode=require';

export const sql = neon(connectionString);

export async function recordAuditLog({
  eventType,
  tableId = null,
  reservationId = null,
  waitlistId = null,
  guestName = null,
  partySize = null,
  statusCode = 200,
  details = ''
}) {
  try {
    await sql`
      INSERT INTO audit_logs (
        event_type, table_id, reservation_id, waitlist_id, guest_name, party_size, status_code, details, created_at
      ) VALUES (
        ${eventType}, ${tableId}, ${reservationId}, ${waitlistId}, ${guestName}, ${partySize}, ${statusCode}, ${details}, NOW()
      )
    `;
  } catch (err) {
    console.error('Failed to write audit log:', err);
  }
}

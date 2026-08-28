/**
 * A passkey as listed by GET /api/me/passkeys (#694). The credential id is an
 * identifier, not a secret; the public key is never exposed to the UI.
 */
export interface Passkey {
  id: number;
  label: string | null;
  credential_id: string;
  created_at: string;
}

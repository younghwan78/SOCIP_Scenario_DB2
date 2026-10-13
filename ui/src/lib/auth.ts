import { useSyncExternalStore } from 'react'

// Credentials live only in this JavaScript session; never write them to browser storage.
export interface ApiCredential { keyId: string; secret: string }
let credential: ApiCredential | null = null
let version = 0
const listeners = new Set<() => void>()
export function setApiCredential(value: ApiCredential | null): void {
  credential = value ? { keyId: value.keyId.trim(), secret: value.secret } : null
  version++
  listeners.forEach((listener) => listener())
}
export const authVersion = () => version
export const credentialKeyId = () => credential?.keyId ?? ''
export function useCredentialKeyId(): string {
  return useSyncExternalStore((listener) => { listeners.add(listener); return () => listeners.delete(listener) }, credentialKeyId, credentialKeyId)
}
export function credentialHeaders(existing?: HeadersInit): Headers {
  const headers = new Headers(existing)
  if (credential) {
    headers.set('X-ScenarioDB-Key-Id', credential.keyId)
    headers.set('X-ScenarioDB-API-Key', credential.secret)
  }
  return headers
}

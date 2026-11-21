export async function getMeta() {
  const response = await fetch('/api/meta')
  if (!response.ok) throw new Error('Gagal memuat konfigurasi.')
  return response.json()
}

export async function recommend(body) {
  const response = await fetch('/api/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(data.detail || 'Permintaan gagal.')
  return data
}
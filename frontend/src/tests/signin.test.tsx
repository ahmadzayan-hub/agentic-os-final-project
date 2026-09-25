import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { SignIn } from '../features/auth/SignIn'
import type { AuthConfig } from '../shared/types'

const CONFIG: AuthConfig = {
  mode: 'jwt',
  provider: 'supabase',
  provider_url: 'https://example.supabase.co',
  publishable_key: 'publishable-anon-key',
  flows: ['password', 'magic_link'],
}

function mockFetch(response: { ok: boolean; body: unknown }) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: response.ok,
    status: response.ok ? 200 : 400,
    json: () => Promise.resolve(response.body),
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('SignIn', () => {
  it('sends credentials to the provider and returns the access token', async () => {
    const fetchMock = mockFetch({ ok: true, body: { access_token: 'token-123' } })
    const onSignedIn = vi.fn()
    const user = userEvent.setup()
    render(<SignIn config={CONFIG} onSignedIn={onSignedIn} />)

    await user.type(screen.getByLabelText('Email'), 'analyst@example.com')
    await user.type(screen.getByLabelText('Password'), 'correct horse battery')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith('token-123'))
    const [url, init] = fetchMock.mock.calls[0]
    // Credentials go to the identity provider, never to this application.
    expect(url).toBe('https://example.supabase.co/auth/v1/token?grant_type=password')
    expect(JSON.parse(init.body as string)).toEqual({
      email: 'analyst@example.com',
      password: 'correct horse battery',
    })
    expect(init.headers.apikey).toBe('publishable-anon-key')
  })

  it('shows the provider error and signs nobody in when credentials fail', async () => {
    mockFetch({ ok: false, body: { error_description: 'Invalid login credentials' } })
    const onSignedIn = vi.fn()
    const user = userEvent.setup()
    render(<SignIn config={CONFIG} onSignedIn={onSignedIn} />)

    await user.type(screen.getByLabelText('Email'), 'analyst@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText('Invalid login credentials')).toBeInTheDocument()
    expect(onSignedIn).not.toHaveBeenCalled()
  })

  it('rejects a provider response that carries no token', async () => {
    mockFetch({ ok: true, body: { user: { id: 'u1' } } })
    const onSignedIn = vi.fn()
    const user = userEvent.setup()
    render(<SignIn config={CONFIG} onSignedIn={onSignedIn} />)

    await user.type(screen.getByLabelText('Email'), 'analyst@example.com')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText(/did not return an access token/)).toBeInTheDocument()
    expect(onSignedIn).not.toHaveBeenCalled()
  })

  it('requests a magic link and confirms where it was sent', async () => {
    const fetchMock = mockFetch({ ok: true, body: {} })
    const user = userEvent.setup()
    render(<SignIn config={CONFIG} onSignedIn={vi.fn()} />)

    await user.type(screen.getByLabelText('Email'), 'analyst@example.com')
    await user.click(screen.getByRole('button', { name: 'Email me a link' }))

    expect(await screen.findByText(/Check analyst@example.com/)).toBeInTheDocument()
    expect(fetchMock.mock.calls[0][0]).toBe('https://example.supabase.co/auth/v1/otp')
  })

  it('explains the problem when the server advertises no usable flow', () => {
    render(
      <SignIn
        config={{ ...CONFIG, flows: [], provider_url: '', publishable_key: '' }}
        onSignedIn={vi.fn()}
      />,
    )
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
    expect(screen.getByText(/no provider is configured/)).toBeInTheDocument()
  })
})

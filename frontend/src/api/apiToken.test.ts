import { beforeEach, describe, expect, it } from 'vitest'

import {
  API_TOKEN_STORAGE_KEY,
  apiTokenHeaders,
  getApiToken,
  isApiTokenRejection,
  storeApiToken,
} from './apiToken'

beforeEach(() => {
  localStorage.clear()
})

describe('API token storage', () => {
  it.each([
    ['a trailing newline', 'operator-secret\n'],
    ['leading whitespace', ' \toperator-secret'],
  ])('removes %s before storing or sending a token', (_description, token) => {
    storeApiToken(token)

    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBe('operator-secret')
    expect(apiTokenHeaders()).toEqual({ Authorization: 'Bearer operator-secret' })
  })

  it('treats whitespace-only input as no token', () => {
    storeApiToken(' \n\t ')

    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBeNull()
    expect(getApiToken()).toBeNull()
    expect(apiTokenHeaders()).toEqual({})
  })

  it('keeps a clean token unchanged', () => {
    storeApiToken('operator-secret')

    expect(localStorage.getItem(API_TOKEN_STORAGE_KEY)).toBe('operator-secret')
    expect(apiTokenHeaders()).toEqual({ Authorization: 'Bearer operator-secret' })
  })
})


describe('isApiTokenRejection', () => {
  it('recognizes only 401 responses carrying a Bearer authentication challenge', () => {
    expect(isApiTokenRejection(new Response(null, {
      status: 401,
      headers: { 'WWW-Authenticate': 'Bearer' },
    }))).toBe(true)
    expect(isApiTokenRejection(new Response(null, {
      status: 401,
      headers: { 'WWW-Authenticate': 'Bearer realm="api"' },
    }))).toBe(true)
    expect(isApiTokenRejection(new Response(null, {
      status: 401,
      headers: { 'WWW-Authenticate': 'bearer' },
    }))).toBe(true)

    expect(isApiTokenRejection(new Response(null, { status: 401 }))).toBe(false)
    expect(isApiTokenRejection(new Response(null, {
      status: 401,
      headers: { 'WWW-Authenticate': 'Basic realm="api"' },
    }))).toBe(false)
    for (const status of [200, 403, 500]) {
      expect(isApiTokenRejection(new Response(null, {
        status,
        headers: { 'WWW-Authenticate': 'Bearer' },
      }))).toBe(false)
    }
  })
})

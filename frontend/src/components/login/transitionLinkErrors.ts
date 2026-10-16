export const TRANSITION_LINK_ERROR_MESSAGES: Record<string, string> = {
  TRANSITIONPASSWORD_INVALID: 'The link password is incorrect.',
  TRANSITION_USERID_INVALID:
    'No account was found for that Trainer ID, or no link password has been set for it in-game.',
  TRANSITION_USER_NOT_EXIST:
    'That Trainer ID cannot be linked. Check the ID and confirm a link password is set on the account in-game.',
  TRANSITION_COMPLETED_ERROR:
    'The link may have partially applied. Re-run plain Steam login and do not retry the link blindly.',
  ACCOUNT_UDID_CONFLICT:
    'This device may already be bound after a partial link. Re-run plain Steam login and do not retry the link blindly.',
  PC_ACCOUNT_LIMIT_ERROR: 'This Steam account has reached the PC account link limit.',
  STEAM_ACCOUNT_REMOVE_CHAINED:
    'This Steam account is still linked elsewhere and cannot be linked here.',
  MAINTENANCE_TASK_ACCOUNT_SIGN_UP:
    'New account setup is temporarily unavailable for maintenance.',
  MAINTENANCE_TASK_DATA_LINKAGE:
    'Trainer-ID data linking is temporarily unavailable for maintenance.',
  MAINTENANCE_TASK_ACCOUNT_CHAIN:
    'Account linking is temporarily unavailable while account-chain maintenance is running.',
  TRANSITION_OLD_ACCESS_ERROR:
    'This link password can no longer be used from the current account.',
  INVALID_PARAMETER_ERROR: 'The Trainer ID or link password is invalid.',
  USER_NOT_FOUND: 'No account was found for that Trainer ID.',
  NO_PLATFORM_USER_ID_ERROR: 'The target account has no platform user ID to link.',
  NO_CHAINED_USER_ID_ERROR: 'The target account has no linked user ID available.',
  RECOVERY_PREFLIGHT_ACCOUNT_UNAVAILABLE:
    'No different local account with valid game auth and Steam sign-in is available to verify recovery.',
  RECOVERY_PREFLIGHT_FAILED:
    'The Trainer ID and link-password recovery route could not be verified.',
  TARGET_STEAM_SESSION_UNAVAILABLE:
    'This account could not establish the Steam-authenticated session required to remove the link.',
  STEAM_UNBIND_FAILED: 'Steam rejected the request to remove this account link.',
  STEAM_UNBIND_STATE_SAVE_FAILED:
    'The Steam link was removed, but the local unbound status could not be saved.',
}

export function transitionLinkErrorMessage(errorCode?: string, detail?: string): string {
  if (errorCode && TRANSITION_LINK_ERROR_MESSAGES[errorCode]) {
    return TRANSITION_LINK_ERROR_MESSAGES[errorCode]
  }
  if (errorCode?.startsWith('MAINTENANCE_TASK_')) {
    return 'Account linking is temporarily unavailable for maintenance.'
  }
  return detail || 'Account linking failed.'
}

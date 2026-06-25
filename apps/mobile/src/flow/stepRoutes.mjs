import { appSectionForStep } from './orderViewState.mjs';

const STEP_TO_ROUTE = {
  auth: '/sign-in',
  pending: '/pending',
  customer: '/customer',
  groups: '/order',
  summary: '/summary',
  success: '/success',
  history: '/history',
  detail: '/detail',
  profile: '/profile',
};

const ROUTE_TO_STEP = Object.fromEntries(
  Object.entries(STEP_TO_ROUTE).map(([step, route]) => [route, step]),
);

export function routeForStep(step) {
  return STEP_TO_ROUTE[step] || STEP_TO_ROUTE.auth;
}

export function stepForRoute(pathname) {
  return ROUTE_TO_STEP[pathname] || 'auth';
}

function isAuthSurfaceStep(step) {
  return step === 'auth' || step === 'pending';
}

export function navigationActionForStep(currentStep, nextStep) {
  if (isAuthSurfaceStep(nextStep)) {
    return 'replace';
  }
  if (nextStep === 'success') {
    return 'replace';
  }
  if (isAuthSurfaceStep(currentStep)) {
    return 'replace';
  }
  // Top-level sections (Order/History/Profile) behave like tabs: switching
  // between them swaps content rather than pushing a back-stack entry.
  if (appSectionForStep(currentStep) !== appSectionForStep(nextStep)) {
    return 'replace';
  }
  return 'navigate';
}

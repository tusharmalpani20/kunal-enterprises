import React, { useContext } from 'react';
import { Redirect } from 'expo-router';

import { restoredSessionRoute } from '../src/domain/sessionFlow.mjs';
import { routeForStep } from '../src/flow/stepRoutes.mjs';
import { AuthContext } from '../src/providers/auth';

export default function IndexRedirect() {
  const { session } = useContext(AuthContext);
  const route = restoredSessionRoute(session);
  return <Redirect href={routeForStep(route.step) as Parameters<typeof Redirect>[0]['href']} />;
}

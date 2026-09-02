import React from 'react';
import { Text } from 'react-native';

import { APP_VERSION_LABEL } from '../constants/appVersion';
import { styles } from '../styles/appStyles';

export function AppVersionFooter() {
  return <Text style={styles.versionFooter}>{APP_VERSION_LABEL}</Text>;
}

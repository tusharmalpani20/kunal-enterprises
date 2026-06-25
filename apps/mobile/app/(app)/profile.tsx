import React from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';
import { UserRound } from 'lucide-react-native';

import { AppShell } from '../../src/components/AppShell';
import { DatePickerButton, ProfileReadOnlyField, Workspace } from '../../src/components/orderUi';
import { useOrderFlow } from '../../src/flow/OrderFlowProvider';
import { styles } from '../../src/styles/orderScreen';

export default function ProfileScreen() {
  const {
    mode,
    profile,
    profileEmail, setProfileEmail,
    profileBirthDate,
    profileAnniversaryDate,
    setDatePickerTarget,
    saveCustomerProfile,
  } = useOrderFlow();

  if (!profile) {
    return <AppShell>{null}</AppShell>;
  }

  return (
    <AppShell>
      <Workspace title="Profile" icon={<UserRound size={18} color="#111111" />}>
        {mode === 'Customer' && (
          <View style={styles.contextBlock}>
            <ProfileReadOnlyField label="Customer Name" value={profile.customer_name} />
            <ProfileReadOnlyField label="Business / Legal Name" value={profile.business_legal_name} />
            <ProfileReadOnlyField label="Mobile Number" value={profile.mobile_number} />
            <Text style={styles.fieldLabel}>Email</Text>
            <TextInput value={profileEmail} onChangeText={setProfileEmail} style={styles.input} />
            <Text style={styles.fieldLabel}>Date of Birth</Text>
            <DatePickerButton
              value={profileBirthDate}
              placeholder="DD-MM-YYYY"
              onPress={() => setDatePickerTarget('profileBirthDate')}
            />
            <Text style={styles.fieldLabel}>Date of Anniversary</Text>
            <DatePickerButton
              value={profileAnniversaryDate}
              placeholder="DD-MM-YYYY"
              onPress={() => setDatePickerTarget('profileAnniversaryDate')}
            />
            <Pressable style={styles.primaryAction} onPress={saveCustomerProfile}>
              <Text style={styles.primaryActionText}>Save profile</Text>
            </Pressable>
          </View>
        )}
        {mode === 'Sales Employee' && (
          <View style={styles.contextBlock}>
            <ProfileReadOnlyField label="Sales Employee Name" value={profile.sales_employee_name} />
            <ProfileReadOnlyField label="Employee Code" value={profile.employee_code} />
            <ProfileReadOnlyField label="Mobile Number" value={profile.mobile_number} />
            <ProfileReadOnlyField label="Status" value={profile.status} />
          </View>
        )}
      </Workspace>
    </AppShell>
  );
}

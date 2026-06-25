export type Step =
  | 'auth'
  | 'pending'
  | 'customer'
  | 'groups'
  | 'summary'
  | 'success'
  | 'history'
  | 'detail'
  | 'profile';

export type AppSection = 'order' | 'history' | 'profile';
export type Mode = 'Customer' | 'Sales Employee';
export type DatePickerTarget =
  | 'signupDateOfBirth'
  | 'signupDateOfAnniversary'
  | 'profileBirthDate'
  | 'profileAnniversaryDate';
export type ToastKind = 'success' | 'error' | 'info';
export type DraftCartSummary = { customer: string; rowCount: number; totalQuantity: number };

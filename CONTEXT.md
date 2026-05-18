# Kunal Enterprise Order System

This context defines the business language for the Tally-connected ordering system used by customers, sales employees, and internal branch users.

## Language

**Product Group**:
The customer-facing first selector for browsing items, backed by the root Tally Stock Group.
_Avoid_: Brand, category, raw stock group

**Root Tally Stock Group**:
A Tally stock group with no parent, used internally to derive the Product Group.
_Avoid_: Brand

**Customer**:
The person/contact placing an order through the mobile app or receiving an order placed by a sales employee.
_Avoid_: Ledger, account

**Customer Business**:
The legal business identity captured during customer signup.
_Avoid_: Customer when referring specifically to legal name/GSTIN

**Client Code**:
The portal-entered customer code/alias used to map the app Customer to the corresponding Tally customer identity.
_Avoid_: Customer ID, ledger ID

**Customer App Access**:
The permission state that allows a Customer to use customer-facing mobile ordering features.
_Avoid_: OTP verification, signup completion

**Mobile Login Identity**:
The unique mobile-number-based identity used for WhatsApp OTP authentication in the mobile app.
_Avoid_: User account when discussing phone-number uniqueness

**Customer Status**:
The lifecycle state controlling customer review and access.
_Avoid_: OTP verification when referring to admin review state

**Customer Assignment**:
An optional inclusive rule that limits which Customers a sales employee can place orders for.
_Avoid_: Customer exclusion

**Sales Employee**:
An admin-created mobile app user who places orders on behalf of Customers.
_Avoid_: Customer, self-signup user

**Order**:
A Frappe-owned customer request for items from one or more godowns, not a stock reservation or Tally invoice.
_Avoid_: Sales order, invoice, reservation

**Order Quantity**:
The requested item quantity on an Order, without price/rate/value.
_Avoid_: Amount, value

**Partial Closure**:
An admin action that closes an Order even though only part of the requested quantity was fulfilled.
_Avoid_: Completed, cancelled

**Fulfillment Signal**:
A Tally Delivery Challan or Sales Invoice line that proves requested quantity has been processed.
_Avoid_: Stock movement when discussing order status

**Manual Review Reason**:
A human-readable explanation for why an Order could not be reconciled automatically.
_Avoid_: Error, failure

**Item Access**:
An inclusive Product Group rule that controls which items a Customer or sales employee can order.
_Avoid_: Stock hiding rule

**Tally Customer**:
The customer identity maintained in Tally, usually represented by business name and alias/client code.
_Avoid_: App user

## Relationships

- A **Product Group** maps to exactly one **Root Tally Stock Group**.
- A **Root Tally Stock Group** can contain many child Tally stock groups and many items through that hierarchy.
- A **Customer** has one **Customer Business** profile.
- A **Customer** can be mapped to one **Tally Customer** through a **Client Code**.
- A **Customer** can have **Customer App Access** only when a **Client Code** is present and access is approved.
- A **Mobile Login Identity** can belong to either one **Customer** or one sales employee, never both.
- A **Sales Employee** is always created by an internal portal user and never self-registers.
- An **Order** does not reduce or reserve Tally stock.
- An **Order** does not store pricing, rates, discounts, tax, or value in Frappe.
- An **Order** is fulfilled later through Tally Delivery Challan and/or Sales Invoice reconciliation.
- A **Partial Closure** can be applied when the remaining quantity will not be supplied.
- A **Fulfillment Signal** from Sales Invoice is primary when present; Delivery Challan is provisional unless no invoice exists.
- Fulfillment matching is item-wise, not godown-wise, because operations may fulfill from a different godown than originally selected.
- An **Order** in Manual Review must have at least one **Manual Review Reason**.
- A sales employee with no **Customer Assignment** can place orders for all active Customers.
- A sales employee with **Customer Assignments** can place orders only for assigned active Customers.
- For sales employee orders, effective **Item Access** is the intersection of sales employee access and Customer access.
- Empty **Item Access** means all Product Groups are visible.
- A **Customer** becomes Active only after mobile verification, admin approval, and Client Code entry.

## Example Dialogue

> **Dev:** "Should the customer choose a category before selecting an item?"
> **Domain expert:** "No, the customer chooses a **Product Group**. Internally that means the root Tally stock group."

> **Dev:** "Is the Customer the same as the Tally ledger?"
> **Domain expert:** "No. The **Customer** is the person placing the order. The **Client Code** maps that customer to the **Tally Customer** alias."

> **Dev:** "Can an admin approve access before adding the client code?"
> **Domain expert:** "No. **Customer App Access** requires a **Client Code**. If the code is removed, access is removed."

> **Dev:** "Can the same mobile number be used for a Customer and a sales employee?"
> **Domain expert:** "No. The mobile number is the **Mobile Login Identity**, so it must be globally unique."

> **Dev:** "Can a sales employee show an item that the Customer is not allowed to see?"
> **Domain expert:** "No. Their effective **Item Access** is the intersection of employee and Customer access."

## Flagged Ambiguities

- "Brand", "category", and "group" were all used for the first item selector. Resolved: the customer-facing term is **Product Group**, backed by **Root Tally Stock Group**.
- "Customer" can mean app user/contact or Tally customer. Resolved: **Customer** means the person/contact in the app; **Tally Customer** means the Tally-side identity.
- "Approved", "portal access", and "app access" can be confused. Resolved: admins can see/edit signup records in the portal; **Customer App Access** is only allowed when **Client Code** is present and access is approved.
- "Unique mobile number" applies across both Customers and sales employees, not only within one table.

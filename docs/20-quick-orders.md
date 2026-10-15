# Quick orders

Customers and Sales Employees can paste or type free-form order text in the mobile
app. Submission creates a **Quick Order Request**, not a placed Order. Sales
Employees must select an allowed active Customer first; the request records the
employee from the authenticated token. Customers can view every request for their
account, while Sales Employees can view only their own requests for customers they
can currently access. Editing and cancellation are not provided in this version.

The request stores read-only Order Source, Sales Employee and Sales Employee Name
fields. Source and employee identity cannot be changed after submission. Existing
customer requests default to Customer source. Conversion preserves the employee
on the normal Order and rechecks current customer and product access.

Requests progress through **Pending Review**, **In Review**, and **Converted to
Order**. Coordinators can also reject an unconverted request, with a required
reason. Customer text remains unchanged as the source of the request.

## Portal party details

Quick Order forms group Request Details, Customer Details, Sales Employee Details,
Order Request, and Review and Order into sections. Read-only fetched details show
customer name, business name, Party Code (Customer Client Code), mobile number and
GSTIN; employee details show name, Employee Code and mobile number. The employee
section is hidden for customer-submitted requests. These extra party fields are
portal-only and are not added to mobile API responses.

A post-model-sync patch fills existing requests from their linked masters without
changing request text, status, source identity, timestamps, order links or audit
history. New requests use standard fetch fields. Schema and patch ship with the
app and run through `bench migrate`.

## Portal review

The Operation workspace contains Quick Order Requests, Pending Quick Orders,
and Quick Orders In Review. An **Order Coordinator**, Owner, or Admin starts
review, manually selects allowed active products and quantities, and clicks
**Place Order**. Godowns are optional. Text is not automatically parsed or
matched to products in this version.

Conversion uses the existing order placement service and its customer product
access, quantity validation, confirmation, and notification behavior. The
resulting Order is Placed; quantities without godowns enter the existing
assignment queue. The request and Order each retain a read-only link to the
other. Conversion is atomic and locks the request so concurrent or repeated
conversion cannot create a second Order. Converted requests stay converted
when the linked Order later changes fulfilment status or is cancelled.

The Order Coordinator role profile includes **Order Coordinator** and **Godown
Allocator**. Owner and Admin profiles also include Order Coordinator. Roles,
profiles, and workspace shortcuts are app fixtures, applied by `bench migrate`;
the two new DocTypes and Order backlink are standard app metadata.

## Mobile testing

Customer and Sales Employee navigation contains Orders, History, and Profile. The Quick Order text
button beside Search products opens a modal. Sales Employees see it only after
selecting a Customer, with the heading **Quick Order for [Customer Name]**. Outside taps, the close button,
and Android Back offer an app-themed Discard or Keep Editing dialog when a draft
has text. Back or tapping outside that warning returns to editing. Dismissal
is blocked during submission; a successful submission clears the draft, closes
the modal, and shows a brief Request sent toast. Failed submissions keep the
draft open for retry.

Both Customer and Sales Employee History combine regular Orders and unconverted Quick Order Requests,
newest first with shared pagination. Converted requests appear once as their
Order, marked with a Quick Order badge. History cards display the actual document
ID, and Sales Employee orders have a separate Sales Employee badge. Unconverted requests
open their original note and review status; converted Orders include an Order
Note tab with the original text. Unconverted request details show one selected
Order Note tab in the same style. Employee History spans their own currently
authorized customers, with customer names and source labels. Switching customers
clears the draft and ignores late results from the previous customer.

Mobile work is code-only. Verify on a phone that a Customer can submit text,
see request status/rejection reason, and open the linked Order after conversion.
Also verify that a Sales Employee can select a customer, submit on their behalf,
and see the request in History and its source in the portal. Requests cannot be edited
or cancelled after submission. Server identity checks apply even if someone
calls the API directly.

Rejection does not require completing unfinished review rows. If unsaved item
changes exist, the portal asks whether to discard them and reject or continue
editing. Converted and rejected requests preserve their item labels and row
identities as well as their quantities. Mobile linked-order reads ignore late
responses after account or navigation changes. Unified History and converted Order
detail reads use the same navigation/account guards, and repeated Load more taps
are blocked while a page is in flight. Mutation responses are constructed before
releasing their savepoint, so a response failure also rolls back the request or conversion.

Pasted text, including HTML-looking content and line breaks, is stored and shown
as literal plain text. Only surrounding whitespace is trimmed on submission.
The portal displays this source in a read-only Text Editor control, escaping
the text for display without changing the stored source or mobile API response.

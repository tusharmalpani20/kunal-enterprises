# Quick orders

Customers can paste or type free-form order text in the mobile app. Submission
creates a **Quick Order Request**, not a placed Order. Sales employees cannot
submit or retrieve these requests using their mobile identity. Customers can
view their own request history and details; editing and cancellation are not
provided in this version.

Requests progress through **Pending Review**, **In Review**, and **Converted to
Order**. Coordinators can also reject an unconverted request, with a required
reason. Customer text remains unchanged as the source of the request.

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

Customer navigation contains Orders, History, and Profile. The Quick Order text
button beside Search products opens a modal. Outside taps, the close button,
and Android Back offer an app-themed Discard or Keep Editing dialog when a draft
has text. Back or tapping outside that warning returns to editing. Dismissal
is blocked during submission; a successful submission clears the draft, closes
the modal, and shows a brief Request sent toast. Failed submissions keep the
draft open for retry.

Customer History combines regular Orders and unconverted Quick Order Requests,
newest first with shared pagination. Converted requests appear once as their
Order, marked with a Quick Order badge. History cards display the actual document
ID, and Sales Employee orders have a separate Sales Employee badge. Unconverted requests
open their original note and review status; converted Orders include an Order
Note tab with the original text. Unconverted request details show one selected
Order Note tab in the same style. Sales Employee history remains an Order list.

Mobile work is code-only. Verify on a phone that a Customer can submit text,
see request status/rejection reason, and open the linked Order after conversion.
A Sales Employee must have no Quick Order navigation. Requests cannot be edited
or cancelled after submission. Server identity checks apply even if someone
calls the API directly.

Rejection does not require completing unfinished review rows. If unsaved item
changes exist, the portal asks whether to discard them and reject or continue
editing. Converted and rejected requests preserve their item labels and row
identities as well as their quantities. Mobile linked-order reads ignore late
responses after account or navigation changes.

Pasted text, including HTML-looking content and line breaks, is stored and shown
as literal plain text. Only surrounding whitespace is trimmed on submission.
The portal displays this source in a read-only Text Editor control, escaping
the text for display without changing the stored source or mobile API response.

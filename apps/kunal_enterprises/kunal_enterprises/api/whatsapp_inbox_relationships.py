"""Read-only, permission-scoped reply and reaction context for the inbox."""
import json
from collections import defaultdict

import frappe
from kunal_enterprises.kunal_enterprises.doctype.order_intake_request.order_intake_request import _sender_key

DT = 'WhatsApp Message'


def reaction_data(source):
    raw = source.get('intake_raw_payload') or {}
    try:
        raw = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        raw = {}
    message = raw.get('message', raw) if isinstance(raw, dict) else {}
    reaction = message.get('reaction') if isinstance(message, dict) else None
    kind = source.get('intake_original_type') or source.get('content_type')
    if not isinstance(reaction, dict) and kind != 'reaction':
        return None
    reaction = reaction if isinstance(reaction, dict) else {}
    return dict(reference=reaction.get('message_id') or source.get('reply_to_message_id'),
        emoji=str(reaction.get('emoji', source.get('message') or '')),
        actor=_sender_key(source.get('from') or source.get('to')))


def _in_chat(source, account, sender):
    field = 'from' if source.type == 'Incoming' else 'to'
    return (source.type in {'Incoming', 'Outgoing'} and source.whatsapp_account == account
        and _sender_key(source.get(field)) == sender and source.has_permission('read'))


def resolve(account, sender, references):
    """Ambiguous and unavailable references intentionally have no target."""
    references = {str(value) for value in references if value}
    if not references:
        return {}
    rows = frappe.get_list(DT, fields=['name', 'message_id'],
        filters={'whatsapp_account': account, 'type': ['in', ['Incoming', 'Outgoing']]},
        or_filters={'name': ['in', list(references)], 'message_id': ['in', list(references)]},
        limit_page_length=0)
    matches = defaultdict(dict)
    for row in rows:
        source = frappe.get_doc(DT, row.name)
        if not _in_chat(source, account, sender):
            continue
        for key in {source.name, source.get('message_id')} & references:
            matches[key][source.name] = source
    return {ref: next(iter(items.values())) for ref, items in matches.items() if len(items) == 1}


def summary(source):
    from kunal_enterprises.api.whatsapp_inbox import _display_text
    return ' '.join(_display_text(source).split())[:240] or {
        'image': 'Photo', 'document': 'Document', 'audio': 'Voice message',
        'video': 'Video', 'location': 'Location', 'contacts': 'Contact',
    }.get(source.get('intake_original_type') or source.get('content_type'), 'Message')


def enrich(sources, items):
    if not sources:
        return items
    # Each call is one account and sender; callers validate before formatting.
    account = sources[0].whatsapp_account
    sender = _sender_key(sources[0].get('from') if sources[0].type == 'Incoming' else sources[0].get('to'))
    references = [source.get('reply_to_message_id') for source in sources]
    events = {source.name: reaction_data(source) for source in sources}
    references += [event['reference'] for event in events.values() if event]
    resolved = resolve(account, sender, references)
    targets = {source.name: source for source in sources}
    targets.update({source.name: source for source in resolved.values()})
    reactions = _reactions(account, sender, list(targets.values()))
    for source, item in zip(sources, items):
        item['direction'] = source.type
        item['reactions'] = reactions.get(source.name, [])
        event = events[source.name]
        ref = event['reference'] if event else source.get('reply_to_message_id')
        target = resolved.get(ref)
        item['reply_context'] = None
        item['reply_to'] = None
        if event:
            item['content_type'] = 'reaction'
            item['reaction'] = dict(target_name=target.name if target else None,
                emoji=event['emoji'], actor=event['actor'], removed=not bool(event['emoji']))
        elif ref:
            item['reply_to'] = target.name if target else 'earlier-message'
            item['reply_context'] = dict(available=bool(target), target_name=target.name if target else None,
                summary=summary(target) if target else 'Original message is not stored',
                sender_name=(target.get('profile_name') or sender) if target and target.type == 'Incoming' else ('Business' if target else ''),
                direction=target.type if target else None,
                missing_reason=None if target else 'Original message is not stored or is unavailable to you.')
    return items


def _reactions(account, sender, targets):
    keys = {key for source in targets for key in (source.name, source.get('message_id')) if key}
    if not keys:
        return {}
    # The capture layer keeps reaction targets in reply_to_message_id. Include
    # raw-only legacy events too, without returning their provider envelopes.
    from kunal_enterprises.api.whatsapp_inbox import _sender_expression
    base = frappe.get_list(DT, fields=['name', 'creation', 'intake_received_at', 'from', 'intake_sender_key', 'intake_original_type', 'content_type', 'reply_to_message_id', 'intake_raw_payload'],
        filters={'whatsapp_account': account, 'type': 'Incoming'}, order_by='', limit_page_length=0, run=False)
    quoted = ','.join(frappe.db.escape(key) for key in keys)
    rows = frappe.db.sql(f"""SELECT r.name FROM ({base}) r WHERE
        {_sender_expression('r')} = {frappe.db.escape(sender)} AND (
        r.reply_to_message_id IN ({quoted}) OR
        CASE WHEN COALESCE(NULLIF(r.intake_original_type, ''), r.content_type) = 'reaction'
            AND JSON_VALID(r.intake_raw_payload)
            THEN JSON_UNQUOTE(JSON_EXTRACT(r.intake_raw_payload, '$.message.reaction.message_id'))
            ELSE NULL END IN ({quoted}))
        ORDER BY COALESCE(r.intake_received_at,r.creation),r.creation,r.name""", as_dict=True)
    events = []
    for row in rows:
        source = frappe.get_doc(DT, row.name)
        if _in_chat(source, account, sender):
            event = reaction_data(source)
            if event:
                events.append(event)
    # Resolve provider IDs with the same duplicate/ACL rules as quoted replies.
    mapping = resolve(account, sender, [event['reference'] for event in events])
    # Provider timestamps keep a delayed old reaction from resurrecting a
    # reaction that the sender has already changed or removed.
    latest = {}
    for event in events:
        target = mapping.get(event['reference'])
        if target:
            latest[(target.name, event['actor'])] = event['emoji']
    grouped = defaultdict(lambda: defaultdict(list))
    for (target, actor), emoji in latest.items():
        if emoji:
            grouped[target][emoji].append(actor)
    return {target: [dict(emoji=emoji, count=len(actors), actors=actors) for emoji, actors in emojis.items()]
        for target, emojis in grouped.items()}


def is_quoted_in_chat(source, account, sender):
    """Outgoing history is exposed only as context of a visible incoming event."""
    keys = [key for key in (source.name, source.get('message_id')) if key]
    rows = frappe.get_list(DT, fields=['name'], filters={'whatsapp_account': account,
        'type': 'Incoming', 'reply_to_message_id': ['in', keys]}, limit_page_length=0)
    return any(_in_chat(frappe.get_doc(DT, row.name), account, sender) for row in rows)

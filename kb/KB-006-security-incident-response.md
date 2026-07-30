# KB-006: Security Incident Response — READ FIRST

**Prime directive: support does not troubleshoot suspected security incidents.** No runbooks, no restart advice, no "try this first." Immediate escalation to the security team, every time.

**Treat as a security incident (non-exhaustive):**
- Phishing link clicked, or credentials entered on a suspicious site
- Unexpected attachments opened, followed by ANY change in system behavior
- Files renamed/encrypted, ransom or "how to recover" notes
- Browser hijack symptoms: self-opening tabs, changed homepage, fake virus warnings
- Reports of spoofed email appearing to come from the client's domain
- Vendor emails requesting changes to bank/payment details (BEC / wire-fraud pattern)
- User denies causing their own account lockout or password-change notices

**Narrow exception — an already-verified payment change.** A request to change bank or payment details is not by itself an incident when the ticket states that *all* of the following happened: the requester contacted the vendor back through a channel already on file with us — not a number, address, or link supplied in the request itself; the person who confirmed it was already known to the business; and the change was approved internally. Verification asserted *inside* the request does not count, and neither does a callback to contact details the request provided. If any element is missing, absent, or merely claimed, treat it as an incident. Urgency, a deadline, a frozen-account story, or an unusual contact channel overrides this exception outright.

**Why no troubleshooting:** restarts and "quick fixes" can destroy forensic evidence, and helpful-sounding advice (e.g., "just reset your password") is insufficient during active compromise — the security team must revoke sessions, verify MFA, and review logs.

**Priority:** always high or critical. Active compromise (credentials entered, ransomware, ongoing fraud) = critical, tier 3, security team.

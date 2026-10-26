# Incident Response Plan

## Purpose

This plan defines how the company responds to operational and security incidents. The Security Policy requires suspected security incidents to be reported to security@example.com within 1 hour; this document describes what happens after that report.

## Severity Levels

- SEV1: full outage of a customer-facing service, confirmed data breach, or active attack. Highest urgency.
- SEV2: major degradation affecting many customers, or a suspected breach under investigation.
- SEV3: minor degradation, a single-customer impact, or a security weakness with no evidence of exploitation.
- SEV4: cosmetic issues and near misses, tracked for learning.

Severity is set by the first responder and may be changed by the incident commander as facts emerge.

## Response Targets

- SEV1 incidents must be acknowledged by the on-call engineer within 15 minutes of the page, and a status update must be posted every 30 minutes until resolution.
- SEV2 incidents must be acknowledged within 1 hour, with status updates every 2 hours.
- SEV3 incidents are acknowledged by the next business day.
- SEV4 incidents are handled in the normal backlog.

## Roles

The incident commander coordinates the response, makes decisions, and keeps the timeline. The communications lead posts internal updates in the #incidents channel and drafts customer messaging. The scribe records actions and times. For security incidents, a member of the Security team joins as the security lead. The incident commander must not also be the person performing technical repairs.

## Communication

All incidents are tracked in the #incidents channel with a thread per incident. SEV1 and SEV2 incidents also get a dedicated video war room. Customer-facing status page updates for SEV1 incidents are published within 60 minutes of declaration. If personal data is confirmed to be affected, affected customers and regulators are notified within 72 hours, coordinated by Legal.

## Evidence Handling

Do not delete, rotate, or modify logs related to an active incident. Snapshots of affected systems are taken before remediation when it is safe to do so. Evidence is stored in the restricted incident bucket, which is covered by legal hold procedures in the Data Retention Policy.

## Postmortems

Every SEV1 and SEV2 incident requires a blameless postmortem document published within 5 business days of resolution. The postmortem includes a timeline, root cause, customer impact, and action items with owners and due dates. Action items are reviewed in the weekly reliability meeting until closed. SEV3 incidents receive a short write-up at the responder's discretion.

## On-Call

On-call rotations are weekly, from Monday 09:00 to the following Monday 09:00. Engineers on call receive a stipend of $300 per week in addition to salary. Secondary on-call is paged if the primary does not acknowledge within the response target. Swaps must be recorded in the scheduling tool.

## Training and Drills

All engineers complete incident response training during onboarding and take part in a tabletop exercise at least twice per year. The plan is tested with a game-day exercise every quarter.

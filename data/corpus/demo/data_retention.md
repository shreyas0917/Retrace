# Data Retention Policy

## Purpose

This policy sets how long the company keeps different categories of data and when it must be deleted. Retaining data longer than necessary increases breach impact and storage cost; deleting it too early breaks legal and operational obligations. The Data Retention Officer in the Legal team owns this policy and the retention schedule.

## Retention Schedule

| Data category | Retention period |
| --- | --- |
| Customer account records | 7 years after account closure |
| Financial and tax records | 7 years after the fiscal year ends |
| Application logs (hot storage) | 90 days |
| Application logs (cold archive) | 1 year |
| Security audit logs | 2 years |
| Employee email | 3 years |
| Recruiting records for unsuccessful candidates | 12 months after the decision |
| Database backups | 35 days on a rolling basis |
| Chat messages in public channels | 18 months |

Where law requires a longer period than this schedule, the legal requirement prevails.

## Deletion Requests

Customers may request deletion of their personal data. Verified requests must be completed within 30 days of receipt, with a written confirmation sent to the requester. Requests are logged in the Privacy Request Tracker and handled by the Privacy team. Data that must be retained for legal or financial reasons, such as invoices, is excluded from deletion and the requester is told which categories were retained and why.

## Legal Hold

When litigation or a regulatory investigation is reasonably anticipated, Legal issues a legal hold notice. A legal hold suspends all scheduled deletion for the named data until the hold is lifted in writing. Deleting data that is subject to a legal hold is a serious policy violation. This complements the Security Policy rule that logs tied to an active investigation must not be deleted.

## Exceptions

Teams that need to keep data longer than the schedule allows must file Form DR-4 (Retention Exception Request) with the Data Retention Officer. Exceptions are granted for a maximum of 12 months and must be renewed. Exceptions are never granted for data whose owner has requested deletion.

## Backups

Backups are retained for 35 days and then overwritten. Data deleted from production is therefore fully purged from backups within 35 days of deletion. Restoring a backup to satisfy a deletion request is not required, but restored data must be re-deleted within 7 days.

## Review

The retention schedule is reviewed quarterly by the Data Retention Officer and annually by Legal and Security together. Changes are communicated in the #policy-updates channel and recorded in the schedule's version history.

## Responsibilities

Data owners are responsible for configuring automated deletion in their systems and confirming it in the annual review. Engineering must ensure that log pipelines expire hot logs at 90 days and archive copies at 1 year. Questions go to privacy@example.com.

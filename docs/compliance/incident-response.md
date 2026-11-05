# Incident response

An incident is any unplanned event that takes a cache down, exposes customer data, or makes us miss the uptime tier we sold.

## Steps

1. Say it out loud in the operator channel and name one person as incident lead.
2. Stop the bleeding. That can mean failing over, blocking a client, or taking a node out. Do not debug on the only remaining primary if a replica can take the traffic.
3. Record the start time, the customer impact, and the tier (99.9% or 99.95%) the affected database was on.
4. Fix the cause, or put a mitigation in place and open a follow-up for the cause.
5. Write a short note: what broke, how we noticed, what we did, what we will change. Link the pull request.

## What is not in place yet

- A paging rotation.
- A practiced drill.
- A customer-notification template approved by anyone.

Until those exist, the availability claim in a contract should match what operations can actually staff.

# Availability

The only uptime tiers offered are **99.9%** and **99.95%**. There is no 99.99% or 99.999% tier.

Over 30 days the error budgets are:

| Tier | Unavailability | Minutes |
|---|---|---|
| 99.9% | 0.1% | 43.2 |
| 99.95% | 0.05% | 21.6 |

99.9% is a primary and one replica on two hosts. 99.95% is a primary and one replica in two failure domains, with the failover path actually configured. A single node is not sold on either tier.

A month that spends the budget is a missed tier even if the process is up at the end of the month. The incident note records which tier the database was on.

These numbers are targets for the topology, not a measurement and not a credit policy. Credits, if any, belong in the contract, not in this pack.

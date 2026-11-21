"""Host adapter for the frozen paired driver in its dedicated worker process."""

import pilot_paid

from .preflight_retry import retry_pilot_preflight


class PairedPi(pilot_paid.PaidPi):
    async def _run_formal(self, *args, **kwargs):
        original = pilot_paid.pilot_network

        async def check(environment, node, logs, **options):
            return await retry_pilot_preflight(original, environment, node, logs, **options)

        pilot_paid.pilot_network = check
        try:
            return await super()._run_formal(*args, **kwargs)
        finally:
            pilot_paid.pilot_network = original

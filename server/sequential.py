"""A range that stays honest however often you look at it.

ADR 0010 shipped a fixed-horizon comparison and admitted, in the ADR,
that "the ranges here assume the sample size was fixed in advance, and
peeking at a running experiment invalidates them". That admission was in
a decision record. It was not in the report.

It needed to be, because the assumption is almost always false. Nobody
running a test on their own data fixes the sample size in advance and
then looks exactly once at the end. They look on Tuesday, and again on
Thursday, and they stop when the number looks good — and stopping when
the number looks good is precisely what turns a 5% error rate into
something far worse. Simulated here, peeking a hundred times at a
fixed-horizon interval finds a "real" difference in a third of
experiments where there is no difference at all.

An always-valid range (a confidence sequence) is the fix. It is valid at
every sample size simultaneously rather than at one chosen in advance,
so looking whenever you like — and stopping whenever you like — does not
break it. The price is width: it is roughly half again as wide as the
fixed-horizon interval, and that width is the honest cost of being
allowed to look.

The construction is the normal-mixture confidence sequence (Robbins
1970; Howard et al., *Time-uniform Chernoff bounds*, 2021). The radius
at sample size n is

    σ · √( 2(nρ² + 1) / (n²ρ²) · ln( √(nρ² + 1) / α ) )

with ρ tuned to the sample size where the interval should be tightest.
Written as a multiple of the ordinary standard error it is a drop-in
replacement for the 1.96 in a fixed-horizon interval, which is how this
module exposes it — one factor, one substitution, nothing else in the
comparison changes.

The claim that this actually holds is not taken on faith from the
formula: `tests/test_sequential.py` simulates thousands of experiments
where nothing is happening, peeks at every step, and measures how often
each method cries wolf.
"""

import math

# Two-sided 5%, matching the fixed-horizon interval it sits beside.
DEFAULT_ALPHA = 0.05

# The sample size the sequence is tuned to be tightest at. A confidence
# sequence has to pick one: it is valid everywhere, but tighter near the
# tuning point and wider far from it. 1,000 observations per arm is a
# reasonable middle for the datasets this tool accepts (2 MB, 50,000
# rows), and being wrong about it costs width rather than validity.
DEFAULT_TUNING_SIZE = 1000


def tuning_parameter(target_size=DEFAULT_TUNING_SIZE, alpha=DEFAULT_ALPHA):
    """ρ, chosen to make the sequence tightest around `target_size`.

    The standard choice: ρ² = (−2 ln α + ln(−2 ln α + 1)) / n*.
    """
    if target_size < 1:
        target_size = 1
    term = -2 * math.log(alpha)
    return math.sqrt((term + math.log(term + 1)) / target_size)


def inflation(sample_size, alpha=DEFAULT_ALPHA, target_size=DEFAULT_TUNING_SIZE):
    """How much wider than 1.96 standard errors the honest range is.

    Returns the multiplier that replaces the fixed-horizon z-score. At
    the tuning point it is around 3.0 — about 1.55× the fixed-horizon
    1.96 — and it grows slowly as the sample moves away from that point,
    because a sequence valid at every size cannot be as tight as one
    valid at a single size chosen in advance.
    """
    if sample_size < 1:
        return float("inf")
    rho = tuning_parameter(target_size, alpha)
    scaled = sample_size * rho ** 2
    return math.sqrt((2 * (scaled + 1) / scaled)
                     * math.log(math.sqrt(scaled + 1) / alpha))


def always_valid_range(difference, standard_error, sample_size,
                       alpha=DEFAULT_ALPHA, target_size=DEFAULT_TUNING_SIZE):
    """The difference, bounded so that looking early does not break it.

    `sample_size` is the smaller of the two groups: the sequence is only
    as advanced as its slower arm, and rounding that in the optimistic
    direction would give back the guarantee this exists to provide.
    """
    radius = standard_error * inflation(sample_size, alpha, target_size)
    return difference - radius, difference + radius


def excludes_no_change(low, high):
    return (low > 0 and high > 0) or (low < 0 and high < 0)

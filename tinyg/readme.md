# tinyg

## Setup TinyG board

Previously we used microsteppers with 8 microsteps and 2.8A of current.

The motors are configured as follows:

* Using CTS `$ex=2`
* Motor 1 is the x axis: `$1ma=0`
* Motor 2 and 3 are the y axis: `$2ma=1` and `$3ma=1`
* Motor 4 is not used `$4ma=2` (assigned to Z)
* TinyG microsteps remain `$1mi=4` `$2mi=4` `$3mi=4`. Testing did not find a better setting.
* Axes are normal `$xam=1` `$yam=1`
* Limit switches are disabled `$xsn=0` `$ysn=0`
* Default steps per revolution: 200 (1.8 degrees per step) `$1sa=1.8` etc.
* TPI is around 6.35 per inch, or 4mm pitch `$1tr=4` `$2tr=4` `$3tr=4` (assumes we are in mm mode)
* Jerk maximum is 2000M mm/min^3: `$xjm=2000` `$yjm=2000`. iPhone accelerometer testing showed less post-move ringing than the previous 2500M setting. Note the documentation: "Jerk values that are less than 1,000,000 are assumed to be multiplied by 1 million. This keeps from having to keep track of all those zeros. For example, to enter 5 billion the value '5000' can be entered."
* Velocity is 3000mm/min: `$xvm=3000` `$yvm=3000`. 3100mm/min and higher increased ringing; 2800-2900mm/min did not improve smoothness enough to justify the speed loss.
* Disable queue reporting `$qv=0`
* Disable text verbosity `$tv=0`

The plotter service applies `$xjm=2000`, `$yjm=2000`, `$xvm=3000`, and `$yvm=3000` at startup.

If a complex path still rings too much, the best fallback from testing was `$xjm=1500`, `$yjm=2000`, `$xvm=3000`, `$yvm=3000`, but this is a more aggressive change and should be tested on the actual path before adopting.

Sending GCode:

* Do not use this node library https://github.com/synthetos/node-g2core-api it [does not work](https://github.com/synthetos/node-g2core-api/issues/13)

## Motion testing

`motion_param_harness.py` runs TinyG move sequences while recording iPhone motion data from the local Motion Recorder app. It defaults to the current recommended params and keeps the previous 2500M jerk values only as a legacy comparison.

Ringing is measured from the iPhone `deviceMotion.userAcceleration` stream at about 100Hz:

* Record idle baseline, then fixed X, Y, and diagonal move sequences.
* Remove slow drift with an approximately 200ms rolling mean.
* Score the high-frequency acceleration after each move with settle RMS, settle peak, and settle time.
* Treat motion as ringing while high-frequency acceleration is above `max(0.012g, 4x idle high-frequency RMS)`.

Lower scores are better. The absolute score has run-to-run noise, so compare repeated trials with the same move distance.

## Motion parameter notes

The previous motion params were `$xjm=2500`, `$yjm=2500`, `$xvm=3000`, `$yvm=3000`.

The main result is that reducing jerk to 2000M improves settling while keeping the same useful velocity. On 20mm moves, `$xjm=2000`, `$yjm=2000`, `$xvm=3000`, `$yvm=3000` improved the score from `9.21` to `8.57`, reduced settle RMS from `0.00359g` to `0.00309g`, and reduced peak user acceleration from `0.2055g` to `0.1798g`.

Velocity tests did not justify changing `$xvm`/`$yvm`:

* 3100mm/min increased ringing.
* 2800-2900mm/min did not improve smoothness enough to justify the speed loss.
* 3000mm/min remains the best default until a path-specific planner is tested.

Lower or asymmetric jerk can be useful, but is not the default yet:

* `$xjm=1500`, `$yjm=2000`, `$xvm=3000`, `$yvm=3000` sometimes had the best 25mm settle metrics.
* The result was not enough to replace the simpler symmetric 2000M default before testing real drawing paths.

## Path planner notes

The plotter service now plans incoming `/draw` paths before sending them to TinyG:

* Source paths are read from the image pipeline JSON schema at `continuous_path.points`.
* Source paths are uniformly scaled into the full `100 x 100mm` plotter area with no default margin and y-axis flip unless the request uses `raw: true`.
* The planner rejects out-of-bounds raw paths instead of clamping individual points.
* Consecutive segments shorter than `0.04mm` are dropped.
* Ramer-Douglas-Peucker simplification runs with default `epsilon_mm=0.10`.
* Planned commands are `G1` moves with feed rates based on local turn angle and segment length, instead of the old behavior of sending every point as an equal `G0` move.

On the current `vectors.json` test path, a `0.10mm` epsilon with no margin and `rotate_180` enabled produces `1171` planned points from `5177` source points, keeps the path inside `x=0.282..99.718mm` and `y=0..100mm`, and has an estimated feed-only time of about `80.8s`. In earlier full-path tests, `0.15mm` was slightly faster and smoother than `0.08mm`, but `0.10mm` is a more conservative default for generated portraits until we have visual comparisons with a pen.

## Microstep notes

Microsteps were tested by changing `$1mi`, `$2mi`, and `$3mi` together to `1`, `2`, `4`, and `8`. TinyG was reset after each change, the current physical home position was redefined, and cautious centered moves were run from 1mm upward.

The current `$1mi=4`, `$2mi=4`, `$3mi=4` setting should stay:

* `mi=1` was clearly rougher, especially on 3mm moves.
* `mi=8` was safe, but rang more on small 3mm moves.
* `mi=2` was close to `mi=4`, but not better enough to justify changing.
* In a focused 20mm repeat, `mi=4` averaged `score=8.66`, `settle_rms=0.00309g`, `settle_peak=0.00774g`; `mi=2` averaged `score=8.74`, `settle_rms=0.00314g`, `settle_peak=0.00784g`.

Reset TinyG after changing microsteps. Without a reset and coordinate redefinition, 0,0 can end up in the wrong physical location.

Things to look into:

* What is the ideal current? We can change the trim pots to adjust this. The iPhone tests suggest jerk and microsteps are the first controls to tune; current still needs a physical trim-pot experiment.
* Should the planner add true corner rounding or arc fitting after we compare the `0.10mm` simplified drawings visually?

# Notes

* `^x` (control-x) will reset the TinyG (power cycle, not factory reset).
* Reset after changing microsteps, or 0,0 will end up in a weird location
* Both axes have around 103mm travel.
* "JSON mode is exited any time by sending a line starting with '$', '?' or 'h'"

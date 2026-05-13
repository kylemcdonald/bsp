# tinyg

## Setup TinyG board

Previously we used microsteppers with 8 microsteps and 2.8A of current.

The motors are configured as follows:

* Using CTS `$ex=2`
* Motor 1 is the x axis: `$1ma=0`
* Motor 2 and 3 are the y axis: `$2ma=1` and `$3ma=1`
* Motor 4 is not used `$4ma=2` (assigned to Z)
* All motors set to 8 microsteps: `$1mi=4` `$2mi=4` `$3mi=4` This gives us a little more torque, traded for accuracy.
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

Things to look into:

* What is the ideal current? We can change the trim pots to adjust this.
* What is the ideal number of microsteps for this application? Torque drops at higher microsteps and higher speeds.

Sending GCode:

* Do not use this node library https://github.com/synthetos/node-g2core-api it [does not work](https://github.com/synthetos/node-g2core-api/issues/13)

## Motion testing

`motion_param_harness.py` runs TinyG move sequences while recording iPhone motion data from the local Motion Recorder app. It defaults to the current recommended params and keeps the previous 2500M jerk values only as a legacy comparison.

# Notes

* `^x` (control-x) will reset the TinyG (power cycle, not factory reset).
* Reset after changing microsteps, or 0,0 will end up in a weird location
* Both axes have around 103mm travel.
* "JSON mode is exited any time by sending a line starting with '$', '?' or 'h'"

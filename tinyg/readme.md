# tinyg

Previously we used microsteppers with 8 microsteps and 2.8A of current.

The motors are configured as follows:

* Using CTS `$ex=2`
* Motor 1 is the x axis: `$1ma=0`
* Motor 2 and 3 are the y axis: `$2ma=1` and `$3ma=1`
* Motor 4 is not used `$4ma=2` (assigned to Z)
* All motors set to 8 microsteps: `$1mi=8` `$2mi=8` `$3mi=8`
* Axes are normal `$xam=1` `$yam=1`
* Limit switches are disabled `$xsn=0` `$ysn=0`
* Default steps per revolution: 200 (1.8 degrees per step) `$1sa=1.8` etc.
* TPI is around 6.35 per inch, or 4mm pitch `$1tr=4` `$2tr=4` `$3tr=4` (assumes we are in mm mode)
* Jerk maximum is 200,000,000 mm/min^3  `$xjm=1,000,000,000` `$yjm=1,000,000,000` and higher may be possible doable
* Velocity is 3000mm/min^3 `$xvm=3000` `$yvm=3000`
* Disable queue reporting `$qv=0`
* Disable text verbosity `$tv=0`

Things to look into:

* How many TPI are these screws? We can set the `$1tr` to configure the steps to mm conversion.

* What is the ideal current? We can change the trim pots to adjust this.
* What is the ideal number of microsteps for this application? Torque drops at higher microsteps and higher speeds.
* Power management mode `$1pm` 0=motor disabled, 1=motor always on, 2=motor on when in cycle, 3=motor on only when moving
* Once conversions are correct, we want to set `$xvm` and `$yvm` for the max velocity, then `$xtn` and `$xtm` for min and max travel. https://github.com/synthetos/TinyG/wiki/TinyG-Tuning

Sending GCode:

* Use this node library https://github.com/synthetos/node-g2core-api

# Notes

* `^x` (control-x) will reset the TinyG (power cycle, not factory reset).
* Reset after changing microsteps, or 0,0 will end up in a weird location
* Both axes have around 103mm travel.
* To use soft limits to reset the axes, go to +100 and +100.
* Sending a `?` seems to reset the JSON-response mode back to text-response mode.
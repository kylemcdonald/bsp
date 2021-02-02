WHEN USING THIS LIBRARY WITH THE CHIPKIT IT GAVE ME THE ERROR:
error: 'cli' was not declared in this scope 

cli(); in arduino disables the interupts; 

!!!!!  MY FIX WAS TO COMMENT OUT ALL OF THE 'cli' INSTANCES   !!!!!

THIS MIGHT BE THE WRONG SOLUTION <SEE BELOW> I simply did this beacuse i am afraid to screw up the timings for my 
stepping that is also happening. (i actualy do not know if that would happen or would even be noticeable.... tbd.

more chipkit it is more complex according to this post
http://chipkit.net/forum/viewtopic.php?f=7&t=2508

"The problem here is that sei() and cli() are fine on a simple chip like the AVR with limited interrupt facilities.

On the PIC32 though the interrupts are considerably more complex. You can't just turn them off and turn them on again - you have to record what they were, and then restore them afterwards."

The code supplied by that post is:

	unsigned int oldInterrupts = disableInterrupts();
	//.. your code
	restoreInterrupts(oldInterrupts);

!!!!!  IF MY FIX MESSES THINGS UP, TRY THE ABOVE SOLUTION  !!!!!!!

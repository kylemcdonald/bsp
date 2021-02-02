// writen by Zachary Schoch
// BotLaboratory.com

//This program is intinded to control/run a cartesian motion machine.
//Currently it is a 2axis machine.
//At this time (JANUARY 2021) we are controlling 3 linear axis motors
//(the program only sees two, as two do the same things they are wired to the same pinouts)
// This uses accell stepper to control step-direction type stepper drivers

// listens for commands from the serial port, stores them into a buffer and runs through them

// Relies heavily on the AccellStepper Library from airspace / mike m.
// Uses the wonderfull ByteBuffer library from siggiorn.com

// NOTE: This program was originally written to control a 3 axis machine with other control channels as well.
// There is a large amount of code here that is not appilcable to this device. Most of the comments are from a different use case.

#include "src/AccelStepper/AccelStepper.h"
#include "src/ByteBuffer/ByteBuffer.h"

#include <SPI.h>

AccelStepper stepperY(1, 2, 3); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)
AccelStepper stepperX(1, 4, 5); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)
AccelStepper stepperZ(1, 6, 7); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)

AccelStepper stepperF(1, 10, 11); // PELLET FEED MOTOR

const int extrudePlusPin = 9; // THIS IS THE PIN WE SEND THE SPEED TO THE EXTRUDER MOTOR WITH
const int extrudeMinPin = 8; // THIS IS THE low PIN (aka ground) It is not actualy connected to this at the moment but connected to the ground pin instaed.

int counter = 0;
int counter2 = 0;

volatile int positionIndex = 0; // This is the index to use to grab a postion for th  e path arrays.

unsigned int positionX = 0;
unsigned int positionY = 0;
unsigned int positionZ = 0;
volatile float extrudeDiv = 0;
volatile int speedDiv = 100;

// was great at 65// really want to get the precission up so going to try lower
// precision was great at 20 and 30, but too slow, going to try going back up//Jan 2015.// our points are .03 inches appart. (they are really close)
volatile int smoothing = 20; // HAS BEEN GOOD AT 100 W aprox 0.21 inches between points // for 1/16 step this works well at around 100 with bigger steps// needs to mucho be smaller depending on the step sizes (how high rez the geometry is converted to points)
// going to try it at 15 because our position arrays are for half steps..biggest step possible on my stepper controllers)

float extrudeSpeed = 0;
float extrudeSpeedMAX = 70; // TESTING ONLY!!!// 2017.01.31

volatile int XYmaxSpeed = 6000; //as of 2021.01.27 // base max speed, actual setting later modified when multiplied by (speedDiv/100)
volatile int ZmaxSpeed = 600; // WAS 600// base max speed, actual setting later modified when multiplied by (speedDiv/100)
volatile int FeedMax = 50000; // not used

int XYaccell = 11000; //as of 2021.01.27 //max accell in steps per second per second
int Zaccell = 400; // WAS 400// max accell in steps per second per second

volatile int XYmax = 0; // also XY max speed but used after XYmaxSpeed is multiplied by (speedDiv/100)
volatile int Zmax = 0; // also  Z max speed but used after  ZmaxSpeed is multiplied by (speedDiv/100)
volatile long FeedSpeed = 0;

String inputString = ""; // a string to hold incoming data
boolean stringComplete = false; // whether the string is complete
boolean GO = false;
boolean runExtruder = false; // for manualy running extruder while program off or paused.
boolean FFORWARD = true;
boolean FreeRange = false; // if we are in mode allowing movement bellow our axis 'zero' and above its limit. (for homing)

int FeedForward = -1; // OUR MATERIAL FEED SCREW & THE CURRENT FEED SCREW STEPPER MOTER ARE WIRED SO THAT A NEGATIVE DIRECTION = FORWARD //
int FeedReverse = 1; // OUR MATERIAL FEED SCREW & THE CURRENT FEED SCREW STEPPER MOTER ARE WIRED SO THAT A POSITIVE DIRECTION = REVERSE //

int Xtarget = 0;
int Ytarget = 0;
int Ztarget = 0;
int SMOOTHtarget = 1;

int xt = 0;
int yt = 0;
int zt = 0;
int est = 0;
int mst = 0;
int SMOOTHt = 0;

String Xrecieved = "";
String Yrecieved = "";
String Zrecieved = "";
String ESrecieved = "";
String MSrecieved = "";
String SMOOTHrecieved = "";

char character;
int Xlimit = 10000; // set max steps in X axis // 2021.01.27 using 400 steps per revolution step driver setting. // this is roughly 90% full travel of the physical axis.
int Ylimit = 10000; // set max steps in Y axis // 2021.01.27 using 400 steps per revolution step driver setting. // this is roughly 90% full travel of the physical axis.
int Zlimit = 18811; // set max steps in Z axis //(18561)per 2017.01.30// (16,947) per July 07 2015
// remember from grasshopper we are deviding the Z steps by 2 in order to reduce it to a 4 digit number
// that gets multiplied by 2 when retrieved from the array below

ByteBuffer Xbuffer; // X position buffer
ByteBuffer Ybuffer; // Y position buffer
ByteBuffer Zbuffer; // Z position buffer
ByteBuffer ESbuffer; // ES = Extrusion Speed buffer
ByteBuffer MSbuffer; // MS = Movement Speed buffer
ByteBuffer SMOOTHbuffer; // Smoothing value buffer

void setup() {
    Xbuffer.init(256); // initiliaize the buffer with capacity of 4096 / 2048 bytes
    Ybuffer.init(256);
    Zbuffer.init(256);
    ESbuffer.init(256);
    MSbuffer.init(256);
    SMOOTHbuffer.init(256);

    Serial.begin(115200);

    //  inputString.reserve(200);     // reserve 200 bytes for the inputString:// does not work with chipkit

    Serial.println("_2021_01_27_TEENSY_REMOTE_016g"); // so I can keep track of what is loaded

    stepperX.setMaxSpeed(XYmaxSpeed); // 450
    stepperX.setAcceleration(XYaccell); //ACCELLERATION IN STEPS PER SECOND PER SECOND

    stepperY.setMaxSpeed(XYmaxSpeed); // 450
    stepperY.setAcceleration(XYaccell); //ACCELLERATION IN STEPS PER SECOND PER SECOND

    stepperZ.setMaxSpeed(ZmaxSpeed); // 400
    stepperZ.setAcceleration(Zaccell); //ACCELLERATION IN STEPS PER SECOND PER SECOND  // was 800,
    //was having problem with z slippage due to exessive accell

    stepperF.setMaxSpeed(FeedMax); // 5000
    //stepperF.setSpeed(-FeedMax);  // hopefull this works, no need for accellerations with the feed motor
    stepperF.setAcceleration(90000); //ACCELLERATION IN STEPS PER SECOND PER SECOND// had it off, but is losing lots of steps, trying it on again

    pinMode(extrudePlusPin, OUTPUT);
    pinMode(extrudeMinPin, OUTPUT);

    //delay (500);// thats 1/2 seconds

}

void loop() {
    unsigned long cMillis = millis();

    stepperX.run();
    stepperY.run();
    stepperZ.run();
    stepperF.run(); // PELLET FEED MOTOR

    if (runExtruder == false) {
        extrudeSpeed = sqrt(sq((abs(stepperX.speed()))) + sq((abs(stepperY.speed()))) + sq(((abs(stepperZ.speed())) / 2)));
        extrudeSpeed = (extrudeSpeed / 15); //was 15 //TUNNING// was great at 19, but moving the machine faster now and need more extrusion
        extrudeSpeed = (extrudeSpeed / 2.5); //GEARHEAD COMPENSATION// all motion is now 2.5* more steps per inch than before. //added 2017.01.31
    } //17//18//20
    else {
        extrudeSpeed = extrudeSpeedMAX;
        extrudeDiv = 93; // WHAT SPEED TO RUNS THINGS AT IF WERE MANUALY RUNNING THE EXTRUDER
    }

    //TESTING MAY16 2016// TURN BACK ON
    extrudeSpeed = (extrudeSpeed * (extrudeDiv / 100)); // extrudeDiv is part of the motion comands sent to the chipkit, can vary from one point to annother.

    //was working at 80, then moved the extruder wiring around and added an earth ground and now its full speed at 80...(may15 2016)
    if (extrudeSpeed > 0) {
        extrudeSpeed += 40; //WAS 30 ON 2017.01.31, TRYING 40, BASE EXTRUDE IS TOO SLOW // ORIGINALLY AT 60(FEB 1 2016).... GOING TO TRY 50 TO SEE IF I CAN GET THE SPEED DOWN // ONLY FOR CHIPKIT**
    }
    //20//1//15

    if (extrudeSpeed > extrudeSpeedMAX) {
        extrudeSpeed = extrudeSpeedMAX; // started off at 85 max, seemed a bit excessive. now at 55. can always go up or down // go back to 255 for chipkit
    }
    //** 55 MAX FOR ARDUINO = APPROX 255 FOR CHIPKIT //** // CHIPKIT is 3.3 volt out instead of the 5 volt that the motor controller is looking for for full speed.
    //** Ideally 0 = 0.0 RPM ** AND 255 = MAX RPM // bec. 255 should = 5 volts, when on the chipkit 255 will only be aprox 3.3 volts = NOT MAX RPM

    if (extrudeDiv == 0) {
        extrudeSpeed = 0;
    }
    if (extrudeDiv == 999) {
        extrudeSpeed = 100;
    }

    FeedSpeed = (pow(extrudeSpeed, 6) / 153413400); // raises the extrudeSpeed by a power and then divides it by a big number, see above note
    FeedSpeed = (FeedSpeed * .13); //TESTING// was at 1.3 for awhile, had some jamming with ABS //

    //300
    FeedSpeed = FeedSpeed + 3000; // TESTING / NOT ORIGINALLY HERE AT ALL

    if (GO == false && runExtruder == false) {
        extrudeSpeed = 0; // to make sure the extruder and feed motor both stop when we pause printing.
        FeedSpeed = 0;
    }

    analogWrite(extrudeMinPin, LOW); // for Extruder main motor
    analogWrite(extrudePlusPin, extrudeSpeed); // for Extruder main motor, set the extrusion speed// 255 ON CHIPKIT == ABOUT 100 RPM AT EXTRUDER SCREW

    if (FeedSpeed > FeedMax) {
        FeedSpeed = FeedMax;
    }
    if (extrudeDiv == 0) {
        FeedSpeed = 0; // TRYING TO MAKE SURE THE EXTRUDER IS OFF WHEN I AM MOVING TO HOME AFTER THE PRINT IS DONE!!!
    }
    if (extrudeSpeed == 0) {
        FeedSpeed = 0; // TRYING TO MAKE SURE THE EXTRUDER IS OFF WHEN I AM MOVING TO HOME AFTER THE PRINT IS DONE!!!
    }

    // CONTROLLING THE FEED MOTOR // CONTROLLING THE FEED MOTOR //
    if (cMillis % 1000 == 0) { // EVERY SECOND WE REVERSE THE FEED MOTOR FOR X MILISECONDS
        if (FFORWARD == true) {
            FFORWARD = false;
            stepperF.setCurrentPosition(0); // TESTING
        }
    } else if (cMillis % 100 == 0) { // AFTER 100 MILISECONDS IN REVERSE, WE GO BACK TO FORWARD
        FFORWARD = true;
    }
    if (FFORWARD == true) {
        //stepperF.setSpeed((FeedSpeed) *(FeedForward) ); // sends speed to Feed Motor // for constant speed movement
        //stepperF.setMaxSpeed(100); // testing with accell, jamming as it was without accells
        stepperF.setMaxSpeed(FeedSpeed); // testing with accell, jamming as it was without accells
        stepperF.moveTo(-1000000);
    } else if (FFORWARD == false) {
        //stepperF.setSpeed((FeedSpeed) *(FeedReverse) ); // sends speed to Feed Motor // for constant speed movement

        //stepperF.setMaxSpeed(100); // testing with accell, jamming as it was without accells
        stepperF.setMaxSpeed(FeedSpeed); // testing with accell, jamming as it was without accells
        stepperF.moveTo(1000000);
    }
    // CONTROLLING THE FEED MOTOR // CONTROLLING THE FEED MOTOR //

    while (Serial.available()) {
        volatile long inChar = Serial.read();
        if (isDigit(inChar)) {
            inputString += (char) inChar;
        }
        // convert the incoming byte to a char
        // and add it to the string:

        // PLUS JOGGING THE Y AXIS // PLUS JOGGING THE Y AXIS //
        if (inChar == 'Y') { // upercase 'Y' = jog y axis plus
            if (inputString.toInt() != 0) { //2021.01.15**
                // Yrecieved = (  (inputString.charAt(0))  );
                // yt = Yrecieved.toInt();
                stepperY.setMaxSpeed(XYmaxSpeed); //was XYmaxSpeed //2021.01.15
                Ytarget = (stepperY.currentPosition() + 50); //NEW 2021.01.15
                //Ytarget = (Ylimit ); //ORIGINAL //2021.01.15
                if (Ytarget > Ylimit) {
                    Ytarget = Ylimit; // checking to make sure where not moving off into oblivion
                }
                if (Ytarget < 0) {
                    Ytarget = 0; // checking to make sure where not moving off into oblivion
                }
                stepperY.moveTo(Ytarget);
                stepperY.run();
            }
            inputString = "";
        }
        // PLUS JOGGING THE Y AXIS // PLUS JOGGING THE Y AXIS //

        // MINUS JOGGING THE Y AXIS //MINUS JOGGING THE Y AXIS //
        if (inChar == 'y') { // lowercase 'y' = jog y axis minus
            if (inputString.toInt() != 0) { //2021.01.15**
                stepperY.setMaxSpeed(XYmaxSpeed); //was XYmaxSpeed //2021.01.15
                Ytarget = (stepperY.currentPosition() - 50); //NEW 2021.01.15
                // Ytarget = (0);  //ORIGINAL //2021.01.15
                if (Ytarget > Ylimit) {
                    Ytarget = Ylimit; // checking to make sure where not moving off into oblivion
                }
                if (Ytarget < 0) {
                    Ytarget = 0; // checking to make sure where not moving off into oblivion
                }
                stepperY.moveTo(Ytarget); // TESTING!!!!!! CHANGE BACK TO X XXXX
                stepperY.run(); // TESTING!!!!!! CHANGE BACK TO X XXXX
            }
            inputString = "";
        }
        // MINUS JOGGING THE Y AXIS // MINUS JOGGING THE Y AXIS //

        // PLUS JOGGING THE X AXIS // PLUS JOGGING THE X AXIS //
        if (inChar == 'X') { // upercase 'X' = jog x axis plus
            if (inputString.toInt() != 0) { //2021.01.15**
                stepperX.setMaxSpeed(XYmaxSpeed); //was XYmaxSpeed //2021.01.15
                Xtarget = (stepperX.currentPosition() + 50); //NEW 2021.01.15
                //Xtarget = (Xlimit ); //ORIGINAL //2021.01.15
                if (Xtarget > Xlimit) {
                    Xtarget = Xlimit; // checking to make sure where not moving off into oblivion
                }
                if (Xtarget < 0) {
                    Xtarget = 0; // checking to make sure where not moving off into oblivion
                }
                stepperX.moveTo(Xtarget);
                stepperX.run();
            }
            inputString = "";
        }
        // PLUS JOGGING THE X AXIS // PLUS JOGGING THE X AXIS //

        // MINUS JOGGING THE X AXIS //MINUS JOGGING THE X AXIS //
        if (inChar == 'x') { // lowercase 'x' = jog x axis minus
            if (inputString.toInt() != 0) { //2021.01.15**
                stepperX.setMaxSpeed(XYmaxSpeed); //was XYmaxSpeed //2021.01.15
                Xtarget = (stepperX.currentPosition() - 50); //NEW 2021.01.15
                //Xtarget = (0); //ORIGINAL //2021.01.15
                if (Xtarget > Xlimit) {
                    Xtarget = Xlimit; // checking to make sure where not moving off into oblivion
                }
                if (Xtarget < 0) {
                    Xtarget = 0; // checking to make sure where not moving off into oblivion
                }
                stepperX.moveTo(Xtarget);
                stepperX.run();
            }
            inputString = "";
        }
        // MINUS JOGGING THE X AXIS // MINUS JOGGING THE X AXIS //

        // PLUS JOGGING THE Z AXIS // PLUS JOGGING THE Z AXIS //
        if (inChar == 'Z') { // upercase 'Z' = jog z axis plus
            if (inputString.toInt() != 0) { //2021.01.15**
                stepperZ.setMaxSpeed(ZmaxSpeed); //
                Ztarget = (Zlimit);
                if (Ztarget > Zlimit) {
                    Ztarget = Zlimit; // checking to make sure where not moving off into oblivion
                }
                if (Ztarget < 0) {
                    Ztarget = 0; // checking to make sure where not moving off into oblivion
                }
                stepperZ.moveTo(Ztarget);
                stepperZ.run();
            }
            inputString = "";
        }
        // PLUS JOGGING THE Z AXIS // PLUS JOGGING THE Z AXIS //

        // MINUS JOGGING THE Z AXIS //MINUS JOGGING THE Z AXIS //
        if (inChar == 'z') { // lowercase 'z' = jog z axis minus
            if (inputString.toInt() != 0) { //2021.01.15**
                stepperZ.setMaxSpeed(ZmaxSpeed); //
                //Ztarget = (-50000 );  // ONLY FOR TESTING
                Ztarget = (0);
                if (Ztarget > Zlimit) {
                    Ztarget = Zlimit; // checking to make sure where not moving off into oblivion
                }
                if (Ztarget < 0) {
                    Ztarget = 0; // checking to make sure where not moving off into oblivion
                }
                stepperZ.moveTo(Ztarget);
                stepperZ.run();
            }
            inputString = "";
        }
        // MINUS JOGGING THE Z AXIS // MINUS JOGGING THE Z AXIS //

        // MANUAL RUNNING THE EXTRUDER // MANUAL RUNNING THE EXTRUDER //
        if (inChar == 'E') { // upercase 'E' = run the extruder
            if (inputString.toInt() != 0) { //2021.01.15**
                runExtruder = true;
            }
            inputString = "";
        }
        // MANUAL RUNNING THE EXTRUDER // MANUAL RUNNING THE EXTRUDER //

        // STOP THE JOGGING // STOP THE JOGGING //
        if (inChar == 'j') { // lowercase 'j' is the code to stop jogging
            if (inputString.toInt() != 0) { //2021.01.15**
                runExtruder = false;
                stepperX.stop(); // Stop as fast as possible: sets new target
                stepperX.runToPosition();
                stepperY.stop(); // Stop as fast as possible: sets new target
                stepperY.runToPosition();
                stepperZ.stop(); // Stop as fast as possible: sets new target
                stepperZ.runToPosition();
                Serial.println("F"); //added 2021.01.15
                stepperX.run(); //added 2021.01.15
                stepperY.run(); //added 2021.01.15
                stepperZ.run(); //added 2021.01.15
            }
            inputString = "";
        }
        // STOP THE JOGGING // STOP THE JOGGING //

        if (inChar == 's') { // lowercase 's' is the code for stop or pause
            if (inputString.toInt() != 0) { //2021.01.15**
                GO = false;
            }
            inputString = "";
        }

        if (inChar == 'g') { // A 'g' comes after a movement comand
            if (inputString.toInt() != 0) { //2021.01.15**
                GO = true;

                // grabbing the SMOOTHING TARGET //
                SMOOTHrecieved = ((inputString.charAt(0)));
                SMOOTHt = SMOOTHrecieved.toInt();
                SMOOTHbuffer.putLong(SMOOTHt); // put the value into the buffer

                // grabbing the X AXIS TARGET //
                Xrecieved += ((inputString.charAt(1)));
                Xrecieved += ((inputString.charAt(2)));
                Xrecieved += ((inputString.charAt(3)));
                Xrecieved += ((inputString.charAt(4)));
                Xrecieved += ((inputString.charAt(5)));

                //Xtarget = Xrecieved.toInt();
                xt = Xrecieved.toInt();
                Xbuffer.putLong(xt); // put the value into the buffer

                // grabbing the Y AXIS TARGET //
                Yrecieved += ((inputString.charAt(6)));
                Yrecieved += ((inputString.charAt(7)));
                Yrecieved += ((inputString.charAt(8)));
                Yrecieved += ((inputString.charAt(9)));
                Yrecieved += ((inputString.charAt(10)));

                //Ytarget = Yrecieved.toInt();
                yt = Yrecieved.toInt();
                Ybuffer.putLong(yt); // put the value into the buffer

                // grabbing the Z AXIS TARGET //
                Zrecieved += ((inputString.charAt(11)));
                Zrecieved += ((inputString.charAt(12)));
                Zrecieved += ((inputString.charAt(13)));
                Zrecieved += ((inputString.charAt(14)));

                zt = Zrecieved.toInt(); // multiply z times 2. // we did this to save one place in the length of the numb sent over serial. loss of resolution is trivial
                Zbuffer.putLong(zt); // put the value into the buffer

                // grabbing the EXTRUSION SPEED NUMBERS //
                ESrecieved += ((inputString.charAt(15)));
                ESrecieved += ((inputString.charAt(16)));

                est = ESrecieved.toInt();
                ESbuffer.putLong(est); // put the value into the buffer

                // grabbing the MOVEMENT SPEED NUMBERS //
                MSrecieved += ((inputString.charAt(17)));
                MSrecieved += ((inputString.charAt(18)));

                mst = MSrecieved.toInt();
                MSbuffer.putLong(mst); // put the value into the buffer

                stepperX.run();
                stepperY.run();
                stepperZ.run();
                stepperF.run(); // PELLET FEED MOTOR
            }

            // clear the string for new input:
            inputString = "";
            Xrecieved = "";
            Yrecieved = "";
            Zrecieved = "";
            ESrecieved = "";
            MSrecieved = "";
        }
    }

    if (GO == false) {
        // counter += 1;
        if (cMillis % 100 == 0) {
            Serial.println("A"); // 'A' is the command that tells processing to send more data.
        }
        //2021.01.15    if (counter % 10000 == 0){  // added this because the code would crash when constantly seding "A" s. Now sends them less often.
        //2021.01.15           Serial.println("A"); // 'A' is the command that tells processing to send more data.
        //2021.01.15            counter = 0;
        //2021.01.15     }
    }

    //  if (GO == false && Xbuffer.getSize()<128) { Serial.println("A");}
    //  if (GO == false && Xbuffer.getSize()>128) { Serial.println("B");}

    if (GO == true) {

        if (((abs(stepperX.distanceToGo())) < (smoothing)) && ((abs(stepperY.distanceToGo())) < (smoothing)) && ((abs(stepperZ.distanceToGo())) < (smoothing * 2))) {
            if (Xbuffer.getSize() > 0) {
                Xtarget = Xbuffer.getLong(); // getInt was giving me trouble
            }
            if (Ybuffer.getSize() > 0) {
                Ytarget = Ybuffer.getLong(); // getInt was giving me trouble
            }
            if (Zbuffer.getSize() > 0) {
                Ztarget = ((Zbuffer.getLong()) * 2); // *2 because we are sending all z values at half of actual to save space
            }
            if (ESbuffer.getSize() > 0) {
                extrudeDiv = ESbuffer.getLong(); // Extrusion Speed
            }
            if (MSbuffer.getSize() > 0) {
                speedDiv = MSbuffer.getLong(); // Movement Speed
            }

            if (SMOOTHbuffer.getSize() > 0) {
                SMOOTHtarget = SMOOTHbuffer.getLong(); // smoothing variable

                if (SMOOTHtarget == 1) {
                    smoothing = 180; // WAS 30 //2021 aall were at 175
                } else if (SMOOTHtarget == 2) {
                    smoothing = 180; // WAS 35
                } else if (SMOOTHtarget == 3) {
                    smoothing = 180; // WAS 40
                } else if (SMOOTHtarget == 4) {
                    smoothing = 180; //WAS 30 // testing high for new 2.5x gear reduction
                } else if (SMOOTHtarget == 5) {
                    smoothing = 180; // WAS 50
                } else if (SMOOTHtarget == 6) {
                    smoothing = 180; // WAS 55
                } else if (SMOOTHtarget == 7) {
                    smoothing = 180; // WAS 60
                } else if (SMOOTHtarget == 8) {
                    smoothing = 180; // WAS 65
                } else if (SMOOTHtarget == 9) {
                    smoothing = 180; // WAS 70
                }
            }

            if (Xbuffer.getSize() < 128) {
                counter2 += 1;
                if (counter2 % 2 == 0) { //WAS 5, TESTING AS 1 added this because the code would crash when constantly seding "A" s. Now sends them less often.
                    Serial.println("A"); // When processing recieves the "A" it sends a bunch of data to fill the buffer back up.
                    counter2 = 0;
                }
            }
            //2021.01.27// else {Serial.println("B");} // There is nothing in the Processing code that listens for "B" so there is no reason to have it.
            else {
                /* Serial.print("XTARRRR");
                  Serial.println(Xtarget);
                  Serial.print("YTARRRR");
                  Serial.println(Ytarget);   */
                //Serial.println("B");
            } // There is nothing in the Processing code that listens for "B" so there is no reason to have it.

            //      Serial.println("XBUFFSIZE");
            //    Serial.println(Xbuffer.getSize());

            if (Xtarget > Xlimit) {
                Xtarget = Xlimit; // checking to make sure where not moving off into oblivion
            }
            if (Ytarget > Ylimit) {
                Ytarget = Ylimit;
            }
            if (Ztarget > Zlimit) {
                Ztarget = Zlimit;
            }

            if (Xtarget < 0) {
                Xtarget = 0; // checking to make sure where not moving off into oblivion
            }
            if (Ytarget < 0) {
                Ytarget = 0; // all valid positions are in the POSITIVE space
            }
            if (Ztarget < 0) {
                Ztarget = 0;
            }

            // Calculating and then setting the maximum XYZ movement speeds: Based on the XYmaxSpeed and ZmaxSpeed set
            // in this program and multiplying those by the speedDiv variable recieved per target point.
            // Setting the resulting values to the max speeds for the relative stepper motors.
            // We are controlling the 'speed' of the machine motion by setting the MAX speed. The machine can always move below that setting.

            if (speedDiv < 100) {
                XYmax = int((XYmaxSpeed / ((100 / speedDiv))));
                Zmax = int((ZmaxSpeed / ((100 / speedDiv))));

                stepperX.setMaxSpeed(XYmax); // 400
                stepperY.setMaxSpeed(XYmax); // 400
                stepperZ.setMaxSpeed(Zmax); // 600
            } else if (speedDiv >= 100) {
                XYmax = int(((XYmaxSpeed * (speedDiv / 100))));
                Zmax = int(((ZmaxSpeed * (speedDiv / 100))));

                stepperX.setMaxSpeed(XYmax); // 400
                stepperY.setMaxSpeed(XYmax); // 400
                stepperZ.setMaxSpeed(Zmax); // 600
            }

            //   Serial.print("XTAR");
            //   Serial.println(Xtarget);
            //   Serial.print("YTAR");
            //   Serial.println(Ytarget);

            //2021.01.27//TESTING//ORIGINAL/
            /*    stepperX.moveTo(Xtarget);
                  stepperY.moveTo(Ytarget);
                  stepperZ.moveTo(Ztarget);
            */ //2021.01.27//TESTING//ORIGINAL//

            //2021.01.27//TESTING//TESTING ONLY SETTING X AXIS EQUAL TO Y AXIS
            stepperX.moveTo(Xtarget);
            stepperY.moveTo(Ytarget);
            stepperZ.moveTo(Ztarget);
            //2021.01.27//TESTING//TESTING ONLY SETTING X AXIS EQUAL TO Y AXIS

            analogWrite(extrudeMinPin, LOW); // for Extruder main motor
            analogWrite(extrudePlusPin, extrudeSpeed); // for Extruder main motor, set the extrusion speed

            stepperX.run();
            stepperY.run();
            stepperZ.run();
            stepperF.run(); // PELLET FEED MOTOR
        }
    }

    stepperX.run();
    stepperY.run();
    stepperZ.run();
    stepperF.run(); // PELLET FEED MOTOR

    analogWrite(extrudeMinPin, LOW);
    analogWrite(extrudePlusPin, extrudeSpeed);

}

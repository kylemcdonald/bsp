// Originally by Zachary Schoch (botLaboratory.com)
// Updated by Kyle McDonald (kylemcdonald.net)

#include <SPI.h>

#include "src/AccelStepper/AccelStepper.h"
#include "src/ByteBuffer/ByteBuffer.h"

// settings
volatile int speedDiv = 100;
volatile int smoothing = 20;
volatile int XYmaxSpeed = 6000; //as of 2021.01.27 // base max speed, actual setting later modified when multiplied by (speedDiv/100)
int XYaccell = 11000; //as of 2021.01.27 //max accell in steps per second per second
int Xlimit = 10000; // set max steps in X axis // 2021.01.27 using 400 steps per revolution step driver setting. // this is roughly 90% full travel of the physical axis.
int Ylimit = 10000; // set max steps in Y axis // 2021.01.27 using 400 steps per revolution step driver setting. // this is roughly 90% full travel of the physical axis.
const int bufferSize = 1024;

// this is the home position. on startup we assume this is where we are.
unsigned int positionX = 0;
unsigned int positionY = 0;

// declare and initialize variables used throughout the code
AccelStepper stepperY(1, 2, 3); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)
AccelStepper stepperX(1, 4, 5); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)

int counter = 0;
int counter2 = 0;

volatile int XYmax = 0; // also XY max speed but used after XYmaxSpeed is multiplied by (speedDiv/100)

String inputString = ""; // a string to hold incoming data
boolean stringComplete = false; // whether the string is complete
boolean GO = false;
boolean FreeRange = false; // if we are in mode allowing movement below our axis 'zero' and above its limit. (for homing)

int Xtarget = 0;
int Ytarget = 0;
int SMOOTHtarget = 1;

int xt = 0;
int yt = 0;
int mst = 0;
int SMOOTHt = 0;

String Xrecieved = "";
String Yrecieved = "";
String MSrecieved = "";
String SMOOTHrecieved = "";

char character;

ByteBuffer Xbuffer; // X position buffer
ByteBuffer Ybuffer; // Y position buffer
ByteBuffer MSbuffer; // MS = Movement Speed buffer
ByteBuffer SMOOTHbuffer; // Smoothing value buffer

void setup()
{
    Xbuffer.init(bufferSize); // initiliaize the buffer with capacity of 4096 / 2048 bytes
    Ybuffer.init(bufferSize);
    MSbuffer.init(bufferSize);
    SMOOTHbuffer.init(bufferSize);

    Serial.begin(115200);

    stepperX.setMaxSpeed(XYmaxSpeed); // 450
    stepperX.setAcceleration(XYaccell); //ACCELLERATION IN STEPS PER SECOND PER SECOND

    stepperY.setMaxSpeed(XYmaxSpeed); // 450
    stepperY.setAcceleration(XYaccell); //ACCELLERATION IN STEPS PER SECOND PER SECOND
}

void loop()
{
    unsigned long cMillis = millis();

    stepperX.run();
    stepperY.run();

    while (Serial.available()) {
        volatile long inChar = Serial.read();
        if (isDigit(inChar)) {
            inputString += (char)inChar;
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

                // grabbing the MOVEMENT SPEED NUMBERS //
                MSrecieved += ((inputString.charAt(11)));
                MSrecieved += ((inputString.charAt(12)));

                mst = MSrecieved.toInt();
                MSbuffer.putLong(mst); // put the value into the buffer

                stepperX.run();
                stepperY.run();
            }

            // clear the string for new input:
            inputString = "";
            Xrecieved = "";
            Yrecieved = "";
            MSrecieved = "";
        }
    }

    if (GO == false) {
        if (cMillis % 100 == 0) {
            Serial.print("A"); // 'A' is the command that tells processing to send more data.
        }
    }

    if (GO == true) {

        if (((abs(stepperX.distanceToGo())) < (smoothing)) && ((abs(stepperY.distanceToGo())) < (smoothing))) {
            if (Xbuffer.getSize() > 0) {
                Xtarget = Xbuffer.getLong(); // getInt was giving me trouble
            }
            if (Ybuffer.getSize() > 0) {
                Ytarget = Ybuffer.getLong(); // getInt was giving me trouble
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

            if (Xbuffer.getSize() < (bufferSize / 2)) {
                counter2 += 1;
                if (counter2 % 2 == 0) { //WAS 5, TESTING AS 1 added this because the code would crash when constantly seding "A" s. Now sends them less often.
                    Serial.print("A"); // When processing recieves the "A" it sends a bunch of data to fill the buffer back up.
                    counter2 = 0;
                }
            }

            // clamp targets
            if (Xtarget > Xlimit) {
                Xtarget = Xlimit;
            } else if (Xtarget < 0) {
                Xtarget = 0;
            }
            if (Ytarget > Ylimit) {
                Ytarget = Ylimit;
            } else if (Ytarget < 0) {
                Ytarget = 0;
            }

            // Calculating and then setting the maximum XYZ movement speeds: Based on the XYmaxSpeed set
            // in this program and multiplying those by the speedDiv variable recieved per target point.
            // Setting the resulting values to the max speeds for the relative stepper motors.
            // We are controlling the 'speed' of the machine motion by setting the MAX speed. The machine can always move below that setting.

            if (speedDiv < 100) {
                XYmax = int((XYmaxSpeed / ((100 / speedDiv))));

                stepperX.setMaxSpeed(XYmax); // 400
                stepperY.setMaxSpeed(XYmax); // 400
            } else if (speedDiv >= 100) {
                XYmax = int(((XYmaxSpeed * (speedDiv / 100))));

                stepperX.setMaxSpeed(XYmax); // 400
                stepperY.setMaxSpeed(XYmax); // 400
            }

            stepperX.moveTo(Xtarget);
            stepperY.moveTo(Ytarget);

            stepperX.run();
            stepperY.run();
        }
    }

    stepperX.run();
    stepperY.run();
}

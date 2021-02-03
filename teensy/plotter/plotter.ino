// Originally by Zachary Schoch (botLaboratory.com)
// Updated by Kyle McDonald (kylemcdonald.net)

#include <SPI.h>

#include "src/AccelStepper/AccelStepper.h"
#include "src/ByteBuffer/ByteBuffer.h"

// settings
const int spoonSize = 512;
const int smoothing = 180;
const int XYmaxSpeed = 6000; //as of 2021.01.27 // base max speed, actual setting later modified when multiplied by (speedDiv/100)
const int XYaccell = 11000; //as of 2021.01.27 //max accell in steps per second per second
const int Xlimit = 10000; // set max steps in X axis // 2021.01.27 using 400 steps per revolution step driver setting. // this is roughly 90% full travel of the physical axis.
const int Ylimit = 10000; // set max steps in Y axis // 2021.01.27 using 400 steps per revolution step driver setting. // this is roughly 90% full travel of the physical axis.
const int bufferScale = 6;
const int bufferSize = 256 * (1 << bufferScale);

// this is the home position. on startup we assume this is where we are.
unsigned int positionX = 0;
unsigned int positionY = 0;

// declare and initialize variables used throughout the code
AccelStepper stepperY(1, 2, 3); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)
AccelStepper stepperX(1, 4, 5); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)

int speedDiv = 100;
int XYmax = 0; // also XY max speed but used after XYmaxSpeed is multiplied by (speedDiv/100)

String inputString = ""; // a string to hold incoming data
boolean GO = false;

int readCount = 0;

int Xtarget = 0;
int Ytarget = 0;

int xt = 0;
int yt = 0;
int mst = 0;

String Xrecieved = "";
String Yrecieved = "";
String MSrecieved = "";

char character;

ByteBuffer Xbuffer; // X position buffer
ByteBuffer Ybuffer; // Y position buffer
ByteBuffer MSbuffer; // MS = Movement Speed buffer

void setup()
{
    Xbuffer.init(bufferSize);
    Ybuffer.init(bufferSize);
    MSbuffer.init(bufferSize);

    Serial.begin(115200);

    stepperX.setMaxSpeed(XYmaxSpeed); // 450
    stepperX.setAcceleration(XYaccell); //ACCELLERATION IN STEPS PER SECOND PER SECOND

    stepperY.setMaxSpeed(XYmaxSpeed); // 450
    stepperY.setAcceleration(XYaccell); //ACCELLERATION IN STEPS PER SECOND PER SECOND
}

void loop()
{
    stepperX.run();
    stepperY.run();

    while (Serial.available()) {
        volatile long inChar = Serial.read();
        if (isDigit(inChar)) {
            inputString += (char)inChar;
        }

        if (inChar == 's') { // lowercase 's' is the code for stop or pause
            GO = false;
            Xbuffer.clear();
            Ybuffer.clear();
            MSbuffer.clear();
            inputString = "";
        }

        if (inChar == 'g') { // A 'g' comes after a movement comand
            if (inputString.toInt() != 0) { //2021.01.15**
                GO = true;

                // grabbing the X AXIS TARGET //
                Xrecieved += ((inputString.charAt(0)));
                Xrecieved += ((inputString.charAt(1)));
                Xrecieved += ((inputString.charAt(2)));
                Xrecieved += ((inputString.charAt(3)));
                Xrecieved += ((inputString.charAt(4)));

                //Xtarget = Xrecieved.toInt();
                xt = Xrecieved.toInt();
                Xbuffer.putLong(xt); // put the value into the buffer

                // grabbing the Y AXIS TARGET //
                Yrecieved += ((inputString.charAt(5)));
                Yrecieved += ((inputString.charAt(6)));
                Yrecieved += ((inputString.charAt(7)));
                Yrecieved += ((inputString.charAt(8)));
                Yrecieved += ((inputString.charAt(9)));

                //Ytarget = Yrecieved.toInt();
                yt = Yrecieved.toInt();
                Ybuffer.putLong(yt); // put the value into the buffer

                // grabbing the MOVEMENT SPEED NUMBERS //
                MSrecieved += ((inputString.charAt(10)));
                MSrecieved += ((inputString.charAt(11)));

                mst = MSrecieved.toInt();
                MSbuffer.putLong(mst); // put the value into the buffer

                stepperX.run();
                stepperY.run();

                readCount++;

                if (readCount == spoonSize) {
                    const unsigned short bufferUsage = Xbuffer.getSize() >> bufferScale;
                    Serial.write(bufferUsage);
                    readCount = 0;
                }
            }

            // clear the string for new input:
            inputString = "";
            Xrecieved = "";
            Yrecieved = "";
            MSrecieved = "";
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

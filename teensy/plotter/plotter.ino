// Originally by Zachary Schoch (botLaboratory.com)
// Updated by Kyle McDonald (kylemcdonald.net)

#include <SPI.h>

#include "Ring.h"
#include "src/AccelStepper/AccelStepper.h"

// settings
const int smoothing = 180;
const long baseSpeed = 6000; // base max speed
const int acceleration = 11000; // max acceleration in steps per second per second
const short Xlimit = 10000; // set max steps in X axis, roughly 90% of full travel
const short Ylimit = 10000; // set max steps in Y axis, roughly 90% of full travel
const int bufferSize = 100000;
const short initialX = 5000;
const short initialY = 5000;

// declare and initialize variables used throughout the code
AccelStepper stepperY(1, 2, 3); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)
AccelStepper stepperX(1, 4, 5); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)

String inputString = ""; // a string to hold incoming data
String arg = "";
boolean running = false;

short Xtarget = 0;
short Ytarget = 0;
short maxSpeed = baseSpeed;

struct Point {
    short x, y;
};

Point rawBuffer[bufferSize];
Ring<Point> buffer(rawBuffer, bufferSize);

void setup()
{
    Serial.begin(115200);

    stepperX.setCurrentPosition(initialX);
    stepperX.setMaxSpeed(baseSpeed);
    stepperX.setAcceleration(acceleration);

    stepperY.setCurrentPosition(initialY);
    stepperY.setMaxSpeed(baseSpeed);
    stepperY.setAcceleration(acceleration);

    // points[0] = 1;
    // points[1] = 1;
}

void done()
{
    Serial.print('e');
    running = false;
}

void loop()
{
    stepperX.run();
    stepperY.run();

    // read all the serial data that is available
    while (Serial.available()) {
        const char inChar = Serial.read();

        // continue calling run() while reading
        stepperX.run();
        stepperY.run();

        if (isDigit(inChar)) {
            inputString += inChar;
            continue;
        }
        
        if (inChar == 's') { // 's' sets the speed
            arg = "";
            arg += inputString.charAt(0);
            arg += inputString.charAt(1);
            const long speedPct = arg.toInt();
            maxSpeed = (baseSpeed * speedPct) / 99;
        } else if (inChar == 'p') { // 'p' pauses
            done();
            buffer.clear();
        } else if (inChar == 'g') { // 'g' goes to point
            running = true;
            Point point;
            arg = "";
            arg += inputString.charAt(0);
            arg += inputString.charAt(1);
            arg += inputString.charAt(2);
            arg += inputString.charAt(3);
            arg += inputString.charAt(4);
            point.x = arg.toInt();
            arg = "";
            arg += inputString.charAt(5);
            arg += inputString.charAt(6);
            arg += inputString.charAt(7);
            arg += inputString.charAt(8);
            arg += inputString.charAt(9);
            point.y = arg.toInt();
            buffer.push_back(point);
        }
        inputString = "";
    }

    if (running == true) {

        if (((abs(stepperX.distanceToGo())) < smoothing) && ((abs(stepperY.distanceToGo())) < smoothing)) {

            // update if we can
            if (buffer.size() > 0) {
                Point point = buffer.pop_front();
                Xtarget = point.x;
                Ytarget = point.y;
            } else {
                // otherwise we are done
                done();
                return;
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

            stepperX.setMaxSpeed(maxSpeed);
            stepperY.setMaxSpeed(maxSpeed);

            stepperX.moveTo(Xtarget);
            stepperY.moveTo(Ytarget);

            stepperX.run();
            stepperY.run();
        }
    }
}

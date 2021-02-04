// Originally by Zachary Schoch (botLaboratory.com)
// Updated by Kyle McDonald (kylemcdonald.net)

#include <SPI.h>

#include "Ring.h"
#include "src/AccelStepper/AccelStepper.h"

// settings
int smoothing = 200; // base smoothing
int maxSpeed = 6000; // base max speed
int acceleration = 11000; // base max acceleration in steps per second per second
const short Xlimit = 10000; // set max steps in X axis, roughly 90% of full travel
const short Ylimit = 10000; // set max steps in Y axis, roughly 90% of full travel
const int bufferSize = 100000;
const short initialX = 5000;
const short initialY = 3500;
const int finishDelay = 500; // delay before sending "e"

// declare and initialize variables used throughout the code
AccelStepper stepperY(1, 2, 3); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)
AccelStepper stepperX(1, 4, 5); // (a,b,c) a== type of motor, b & c are pin assignments//1 for a = stepper driver. (ZACH NEEDS a=1)

String inputString = ""; // a string to hold incoming data
String arg = "";
boolean running = false;

elapsedMillis millisNotRunning;
boolean finished = false;

short Xtarget = 0;
short Ytarget = 0;

struct Point {
    short x, y;
};

Point rawBuffer[bufferSize];
Ring<Point> buffer(rawBuffer, bufferSize);

void setup()
{
    Serial.begin(115200);

    stepperX.setCurrentPosition(initialX);
    stepperY.setCurrentPosition(initialY);

    stepperX.setMaxSpeed(maxSpeed);
    stepperY.setMaxSpeed(maxSpeed);

    stepperX.setAcceleration(acceleration);
    stepperY.setAcceleration(acceleration);
}

void stopRunning() {
    running = false;
    finished = false;
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
        
        if (inChar == 's') { // 's' sets the speed (4 digits)
            arg = "";
            arg += inputString.charAt(0);
            arg += inputString.charAt(1);
            arg += inputString.charAt(2);
            arg += inputString.charAt(3);
            maxSpeed = arg.toInt();
            stepperX.setMaxSpeed(maxSpeed);
            stepperY.setMaxSpeed(maxSpeed);
        } else if (inChar =='m') { // 'm' sets the smoothing (3 digits)
            arg = "";
            arg += inputString.charAt(0);
            arg += inputString.charAt(1);
            arg += inputString.charAt(2);
            smoothing = arg.toInt();
        } else if (inChar =='a') { // 'a' sets the acceleration (5 digits)
            arg = "";
            arg += inputString.charAt(0);
            arg += inputString.charAt(1);
            arg += inputString.charAt(2);
            arg += inputString.charAt(3);
            arg += inputString.charAt(4);
            acceleration = arg.toInt();
            stepperX.setAcceleration(acceleration);
            stepperY.setAcceleration(acceleration);
        } else if (inChar == 'p') { // 'p' stops (0 digits)
            stopRunning();
            buffer.clear();
        } else if (inChar == 'g') { // 'g' goes to point (10 digits, 5 per point)
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

    if (running) {

        millisNotRunning = 0;

        // if we are within a box around the target
        int rdx = abs(stepperX.distanceToGo());
        int rdy = abs(stepperY.distanceToGo());
        if (rdx < smoothing && rdy < smoothing) {

            // try to go to the next point
            if (buffer.size() > 0) {
                Point point = buffer.pop_front();
                Xtarget = point.x;
                Ytarget = point.y;
            } else {
                stopRunning();
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

            stepperX.moveTo(Xtarget);
            stepperY.moveTo(Ytarget);

            stepperX.run();
            stepperY.run();
        }
    }

    if (!finished && millisNotRunning > finishDelay) {
        Serial.print('e');
        finished = true;
    }
}

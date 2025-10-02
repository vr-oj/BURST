/***************************************************
 *       ITSY BITSY M4 WITH CUSTOM PCB             *
 *     1.8" LCD TFT ST7735 DISPLAY 128X160.        *
 *             REVISED 29SEP2025 NRT               *
 *   FOR USE WITH SOFTWARE INTERFACE BY OJVR       *  
 ***************************************************/

#include <Wire.h>
#include "bitmaps.h"
#include "FlashStorage.h"
#include "stepper.h"
#include "avr/dtostrf.h"
#include <SPI.h>
#include <Adafruit_GFX.h>
#include "FreeSansBold7pt7b.h"
#include "FreeSansBold8pt7b.h"
#include "FreeSansBold9pt7b.h"
#include <Adafruit_ST7735.h>  // Hardware-specific library

/*ADC Setup*/
ADS1115 ads;
int rawADC;
int rawADC1;
int txdx1 = 0;

//TFT Setup
#define TFT_CS A4
#define TFT_DC A3
#define TFT_RST -1  // Or set to -1 and connect to Arduino RESET pin
Adafruit_ST7735 tft = Adafruit_ST7735(TFT_CS, TFT_DC, TFT_RST);

//Rotary Encoder Setup and interrups
#define pinA 10
#define pinB 11
#define enSW 12
volatile byte aFlag = 0;        //  let's us know when we're expecting a rising edge on pinDT to signal that the encoder has arrived at a detent
volatile byte bFlag = 0;        //  let's us know when we're expecting a rising edge on pinCLK to signal that the encoder has arrived at a detent (opposite direction to when aFlag is set)
int encoderPos;                 //  this variable stores our current value of encoder position. Change to int or uin16_t instead of byte if you want to record a larger range than 0-255
volatile uint32_t reading = 0;  //  somewhere to store the direct values we read from our interrupt pins before checking to see if we have moved a whole detent
uint32_t maskA;
uint32_t maskB;
uint32_t maskAB;
volatile uint32_t *port;
bool box;
int runState = 0;
bool PrintHeader = true;
int choice;
int captureChoice;
int count;

//Stepper Setup
float stepAngle = 1.8;  //in deg. Change depending on stepper; usually 0.9 or 1.8 degress
float acmeLead = 8;     //in mm. Change based on acme lead; 8 mm is common. This is NOT pitch; that's space between threads.
int stepFraction;       //Use the denominator. so for 1/4, use 4; for 1/16 use 16, etc.
float stepDistance;
int stepsDeform;
float preload;  //
float selPreload = 0.000;
Stepper stepper(0, 9, 7, 5, 2, 3);
// #define stepPin 0   //Motor driver pin for stepping.
// #define dirPin 9    //Motor driver pin for motor direction.
// #define enPin 7     //Motor driver pin for engaging. Must be LOW in order to run motor.
// #define vHiPin 5    //Pin to put 5 V over the other pins needed to engage the stepper driver
// //Next two pins determine microstepping. See datasheet for appropriate driver for specs.
// #define m0Pin 2
// #define m1Pin 3
int zeroing;
bool home = false;

//Parameters for constant rate and manual step configurations
float rateFwd;
float rateRev;
float deform;
int dfrm;
int fps;
int GapTime;
int FwdGapTime;
int RevGapTime;
int numCycles;
int expType;
int cycleCount = 0;
int cycleCountTemp = 0;
int toggle = 0;
int counter = 0;
float tracker;  //This tracks the distance traveled after preload in ConstVelCycle
int distCounter = 0;
unsigned long previousTimer = 0;
int step = 0;
bool makeStep = false;
unsigned long currentTimer;
float conTension;
bool counts = true;
char serialOutput[36];
char receivedChar;
bool newData;

void fpinA() {
  noInterrupts();
  reading = *port & maskAB;
  if ((reading == maskAB) && aFlag) {  //check that we have both pins at detent (HIGH) and that we are expecting detent on this pin's rising edge
    encoderPos--;
    box = !box;
    bFlag = 0;  //reset flags for the next turn
    aFlag = 0;  //reset flags for the next turn
  } else if (reading == maskB)
    bFlag = 1;
  interrupts();  //signal that we're expecting pinCLK to signal the transition to detent from free rotation
}
void fpinB() {
  noInterrupts();
  reading = *port & maskAB;
  if (reading == maskAB && bFlag) {  //check that we have both pins at detent (HIGH) and that we are expecting detent on this pin's rising edge
    encoderPos++;
    box = !box;
    bFlag = 0;  //reset flags for the next turn
    aFlag = 0;  //reset flags for the next turn
  } else if (reading == maskA)
    aFlag = 1;
  interrupts();  //signal that we're expecting pinDT to signal the transition to detent from free rotation
}

//Lighting Pins and camera
#define CamTrig A2
#define ledPin 13
int interval = 10;  //time for the camera to trigger high
int cameraFrame = 0;

//FORCE sensor calibration an setup
int CST_FORCE_IN_MIN = 0;            // Raw value calibration lower point
int CST_FORCE_IN_MAX = 65535;         // Raw value calibration upper point
double CST_FORCE_OUT_MIN = 0.00;     // FORCE calibration lower point
double CST_FORCE_OUT_MAX = 1000.00;  // FORCE calibration upper point. This is in mN. This is about the max it can do.
double CAL_FORCE_MIN = 0.00;
double CAL_FORCE_MAX = 5.00;
float low_cal_sel;
float high_cal_sel;
int low_cal_ADC;
int high_cal_ADC;
FlashStorage(lowADC, int);
FlashStorage(lowSel, float);
FlashStorage(highADC, int);
FlashStorage(highSel, float);
FlashStorage(saveLoad, float);
int fpsDelay;             //Time in millis cacluated when selecting the frames per second.

//*****************************************************************************************************************
int timeDelay = 100;                        //  Change this to alter the time delay for wheatstone bridge output. *
const int NUMSAMPLES = 5;                  //  Change this to alter the number of samples averaged.              *
const int filterWeight = 1;                //Change this to alter the weighting of the averaging filter.         *
//*****************************************************************************************************************

uint16_t samples1[NUMSAMPLES];     // Needed to determine how the samples will be summed and averaged.
unsigned long previousMillis = 0;  // Resetting the clock to determine how much time has elapsed.
unsigned long currentMillis;
unsigned long startMillis;
bool UseStartTime = true;
char number[8];
char distTravel[8];
char force[6];
char cycles[3];
char time[12];
double avg;
double currentTime;
float setDef;

// Amplifier txdx1(wsbPin, CST_FORCE_IN_MIN, CST_FORCE_IN_MAX, CST_FORCE_OUT_MIN, CST_FORCE_OUT_MAX);  //  Initialize the Wheatstone bridge object, plugged into Strain2 on the shield

void setup() {
  Serial.begin(460800);
  ads.begin();
  ads.setGain(GAIN_ONE);
  pinMode(enSW, INPUT_PULLUP);
  pinMode(pinB, INPUT_PULLUP);
  pinMode(pinA, INPUT_PULLUP);
  attachInterrupt(pinA, fpinA, CHANGE);  //Sets interrupt for rotary encoder so that it works with above functions;
  attachInterrupt(pinB, fpinB, CHANGE);  //RISING for the black rotary encoder; CHANGE for blue one.
  maskA = digitalPinToBitMask(pinA);
  maskB = digitalPinToBitMask(pinB);
  maskAB = maskA | maskB;
  port = portInputRegister(digitalPinToPort(pinA));
  stepper.begin();
  pinMode(ledPin, OUTPUT);
  pinMode(CamTrig, OUTPUT);
  digitalWrite(CamTrig, LOW);
  digitalWrite(ledPin, HIGH);
  tft.initR(INITR_GREENTAB);
  tft.initR(INITR_BLACKTAB);
  tft.fillScreen(ST7735_BLACK);
  tft.setRotation(1);
  tft.setTextWrap(false);

  bootup();
  calibration();
  lowADC.write(low_cal_ADC);
  lighting();
  ZeroChoice();
  preloading();
  saveLoad.write(preload);
  delay(200);
  testType();
  cameraFPS();
  cameraCapture();
  clickBegin();
  ads.linearCal(low_cal_ADC, high_cal_ADC, low_cal_sel, high_cal_sel);
  setDef = preload + deform;
  stepDistance = stepper.setStepFrac(8, stepAngle, acmeLead);
  stepsDeform = deform / stepDistance;
  FwdGapTime = (1000000 / (rateFwd / stepDistance));
  RevGapTime = (1000000 / (rateRev / stepDistance));
  printWords(7, 1, 6, 122, ST77XX_RED, "STOPPED");
  tft.drawRect(2, 108, 158, 20, ST77XX_RED);
  rowNames();
}
void loop() {
    if (runState == 0) {
      isRunning();
    }
    else if (runState == 1) {
      isStopping();
    }
    else if (runState == 2) {
      FixDefSteps();
    }
}
/*******************************Utility Functions *******************************/
void autoloading() {
  initScreen();
  int ticker = 0;
  encoderPos = 0;
  char buffer[7];
  char buffer2[7];
  stepDistance = stepper.setStepFrac(8, stepAngle, acmeLead);
  stepper.setStepFrac(8, stepAngle, acmeLead);
  while (digitalRead(enSW)) {
    ticker = stepper.load(1, 50000, 1);
    averaging(NUMSAMPLES);
    preload = selPreload + (ticker * stepDistance);
    sprintf(buffer, "%.3f ", preload);
    sprintf(buffer2, "%.2f ", avg);
    printWords(0, 2, 80, 87, ST77XX_WHITE, buffer);
    printWords(0, 2, 80, 106, ST77XX_WHITE, buffer2);
  }
  while (digitalRead(enSW) == 0) {
    selPreload = preload;
  }
}

void averaging(int q) {
  // ads.linearCal(low_cal_ADC, high_cal_ADC, low_cal_sel, high_cal_sel);
  double sample[NUMSAMPLES];
  double avgSample = 0.00;
  uint8_t i;
  for (i = 0; i < NUMSAMPLES; i++) {
    sample[i] = ads.measure(txdx1);
  }
  avgSample = 0;
  for (i = 0; i < NUMSAMPLES; i++) {
    avgSample += sample[i];
  }
  avgSample /= NUMSAMPLES;
  avg = avgSample;
  // for (int i = 0; i < q; i++) {
  //   avg = avg + (Tension - avg) / filterWeight;
  // }
}

void baseline() {
  for (int i=0; i <= (5*fps); i++) {
    averaging(NUMSAMPLES);
    Serial.print("Pre");
    Serial.print(", , , , ");
    Serial.println(avg, 3);
    delay(timeDelay);
  }
}

void bootup() {
  while (digitalRead(enSW)) {
    int h = 128, w = 160, row, col, buffidx = 0;
    for (row = 0; row < h; row++) {
      for (col = 0; col < w; col++) {
        tft.drawPixel(col, row, pgm_read_word(logo + buffidx));
        buffidx++;
      }
    }
    printWords(0, 1, 120, 117, ST77XX_RED, "v4.0");
  }
  while (digitalRead(enSW) == 0) {
    tft.fillScreen(ST77XX_BLACK);
  }
}

void calibration() {
  const char *myMenu[] = { "Load", "New", "BEWARE" };
  encoderPos = 0;
  initScreen();
  while (digitalRead(enSW)) {
    int position = encoderPos;
    if (encoderPos < 0) { position = 0; }
    if (encoderPos > 2) { position = 2; }
    if (position == 0) {
      listBox(79, 27, 80, 14, ST77XX_BLACK);
      printWords(9, 1, 80, 39, ST77XX_WHITE, myMenu[position]);
      choice = position;
    } else if (position == 1) {
      listBox(79, 27, 80, 14, ST77XX_BLACK);
      printWords(9, 1, 80, 39, ST77XX_WHITE, myMenu[position]);
      choice = position;
    } else if (position == 2) {
      listBox(79, 27, 80, 14, ST77XX_BLACK);
      printWords(9, 1, 80, 39, ST77XX_WHITE, myMenu[position]);
      choice = position;
    }
  }
  while (digitalRead(enSW) == 0) {
    printWords(9, 1, 80, 39, 0xfb2c, myMenu[choice]);
  }
  if (choice == 0) {
    low_cal_ADC = lowADC.read();
    low_cal_sel = lowSel.read();
    high_cal_ADC = highADC.read();
    high_cal_sel = highSel.read();
    calWords();
    calNums();
    offset();
    tft.fillScreen(ST77XX_BLACK);
    initScreen();
    printWords(9, 1, 80, 39, 0xfb2c, "Done");
    delay(100);
  }
  if (choice == 1) {
    delay(250);
    calWords();
    low_cal_ADC = forceLowADC();
    delay(100);
    low_cal_sel = forceLowSel();
    delay(100);
    high_cal_ADC = forceHighADC();
    delay(100);
    high_cal_sel = forceHighSel();
    delay(100);
    offset();
    delay(100);
    tft.fillScreen(ST77XX_BLACK);
    initScreen();
    printWords(9, 1, 80, 39, 0xfb2c, "Done");
    delay(100);
  }
  if (choice == 2) {
    tft.fillScreen(ST77XX_BLACK);
    low_cal_ADC = 642;
    low_cal_sel = 0;
    high_cal_ADC = 2522;
    high_cal_sel = 5*9.81;
    highSel.write(high_cal_sel);
    calWords();
    calNums();
    offset();
    tft.fillScreen(ST77XX_BLACK);
    initScreen();
    printWords(9, 1, 80, 39, 0xfb2c, "Done");
    delay(100);
  }
}

void calNums() {
  printNumber(2, 90, 26, ST77XX_WHITE, ST77XX_BLACK, low_cal_ADC);
  printNumber(2, 90, 46, ST77XX_WHITE, ST77XX_BLACK, low_cal_sel);
  printNumber(2, 90, 66, ST77XX_WHITE, ST77XX_BLACK, high_cal_ADC);
  printNumber(2, 90, 86, ST77XX_WHITE, ST77XX_BLACK, high_cal_sel);
}

void calWords() {
  tft.fillScreen(ST77XX_BLACK);
  printWords(9, 1, 36, 19, 0x64df, "Calibration");
  tft.drawFastHLine(2, 24, 158, 0xfe31);
  printWords(9, 1, 2, 39, 0x04d3, "Min ADC:");
  tft.drawFastHLine(2, 44, 158, 0xfe31);
  printWords(9, 1, 2, 59, 0x04d3, "Sel Min:");
  tft.drawFastHLine(2, 64, 158, 0xfe31);
  printWords(9, 1, 2, 79, 0x04d3, "Max ADC:");
  tft.drawFastHLine(2, 84, 158, 0xfe31);
  printWords(9, 1, 2, 99, 0x04d3, "Sel Max:");
  tft.drawFastHLine(2, 104, 158, 0xfe31);
  printWords(9, 1, 2, 119, 0x04d3, "Offset:");
}

void cameraCapture() {
  const char *myString[] = {"None", "Every", "1 in 5", "1 in 10", "1 in 15", "1 in 20", "1 in 25", "1 in 30"};
  encoderPos = 0;
  int capture;
  while (digitalRead(enSW)) {
    encoderLimit(0, 7);
    capture = encoderPos;
    listBox(80, 46, 80, 18, ST77XX_BLACK);
    printWords(9, 1, 80, 59, ST77XX_WHITE, myString[capture]);
    captureChoice = capture;
  }    
  while (digitalRead(enSW) == 0) {
    printWords(9, 1, 80, 59, 0xfb2c, myString[capture]);
  }
}

int cameraFPS() {
  tft.fillScreen(ST77XX_BLACK);
  char buffer[5];
  encoderPos = 0;
  cameraMenu();
  while (digitalRead(enSW)) {
    encoderLimit(0, 6);
    if (encoderPos == 0) {
      fps = 1;      
    }
    else if (encoderPos > 0) {
    fps = encoderPos * 5; }
    sprintf(buffer, "%d ", fps);
    listBox(99, 27, 50, 14, ST77XX_BLACK);
    printWords(9, 1, 100, 39, ST77XX_WHITE, buffer);
  } 
  while (digitalRead(enSW) == 0) {
    printWords(9, 1, 100, 39, 0xfb2c, buffer);
  }
  fpsDelay = 1000 / fps;
  // Serial.println(fps);
  return fps;
}

void cameraMenu() {
  printWords(9, 1, 10, 19, 0x64df, "Camera Settings");
  tft.drawFastHLine(2, 24, 158, 0xfe31);
  printWords(9, 1, 2, 39, 0x04d3, "Fames/s:");
  tft.drawFastHLine(2, 44, 158, 0xfe31);
  printWords(9, 1, 2, 59, 0x04d3, "Capture:");
  tft.drawFastHLine(2, 64, 158, 0xfe31);
  // printWords(9, 1, 2, 79, 0x04d3, "Zero:");
  tft.drawFastHLine(2, 84, 158, 0xfe31);
  // printWords(9, 1, 2, 99, 0x04d3, "Preload:");
  tft.drawFastHLine(2, 104, 158, 0xfe31);
  // printWords(9, 1, 2, 119, 0x04d3, "Type:");
  const char *myMenu[] = { "Load", "New", "Test" };
}

void clickBegin() {
  while (digitalRead(enSW)) {
    printWords(8, 1, 36, 118, 0x64df, "Click to Begin");
  }
  while (digitalRead(enSW) == 0) {
    tft.fillScreen(ST7735_BLACK);
    delay(100);
    runState = 1;
    UseStartTime = true;
    encoderPos = 0;
  }
}

void constVelocity() {
  tft.fillScreen(ST77XX_BLACK);
  encoderPos = 0;
  printWords(9, 1, 4, 19, 0x64df, "Constant Velocity");
  tft.drawFastHLine(2, 24, 158, 0xfe31);
  printWords(9, 1, 2, 39, 0x04d3, "Rate Fwd:");
  tft.drawFastHLine(2, 44, 158, 0xfe31);
  printWords(9, 1, 2, 58, 0x04d3, "Rate Rev:");
  tft.drawFastHLine(2, 64, 158, 0xfe31);
  printWords(9, 1, 2, 79, 0x04d3, "Deform:");
  tft.drawFastHLine(2, 84, 158, 0xfe31);
  printWords(9, 1, 2, 98, 0x04d3, "# Cyles:");
  tft.drawFastHLine(2, 104, 158, 0xfe31);
  SelRateFwd();
  SelRateRev();
  SelDeform();
  SelNumCycles();
}

void ConstVelCycle() {
    currentTimer = micros();
  if ((numCycles > 0) && (cycleCountTemp < numCycles)) {
    if (counts == true) {
      if (currentTimer - previousTimer >= FwdGapTime && (tracker <= setDef)) {
        tracker = tracker + stepDistance;
        stepper.move(1, 0, 1);
        previousTimer = currentTimer;
      }
      if (tracker > setDef) {
        counts = false;
      }
    }
    if (counts == false) {
      if (currentTimer - previousTimer >= RevGapTime && (tracker >= preload)) {
        tracker = tracker - stepDistance;
        stepper.move(1, 0, -1);
        previousTimer = currentTimer;
      }
      if (tracker <= preload) {
        cycleCountTemp++;
        cycleCount++;
        counts = true;
      }
    }
  }
  if ((numCycles > 0) && (cycleCountTemp == numCycles)) {
    cycleCount = numCycles;
    dtostrf(cycleCount, 3, 0, cycles);
    printWords(0, 2, 100, 83, ST77XX_WHITE, cycles);
    toggle = 1;
  }
  if (numCycles == 0) {
    if (counts == true) {
      if (currentTimer - previousTimer >= FwdGapTime && (tracker <= setDef)) {
        tracker = tracker + stepDistance;
        stepper.move(1, 0, 1);
        previousTimer = currentTimer;
      }
      if (tracker > setDef) {
        counts = false;
      }
    }
    if (counts == false) {
      if (currentTimer - previousTimer >= RevGapTime && (tracker >= preload)) {
        tracker = tracker - stepDistance;
        stepper.move(1, 0, -1);
        previousTimer = currentTimer;
      }
      if (tracker <= preload) {
        cycleCountTemp++;
        cycleCount++;
        counts = true;
      }
    }
  }
}

void encoderLimit(int min, int max) {
  if (encoderPos < min) { 
    encoderPos = min; 
  }
  if (encoderPos > max) {
    encoderPos = max;
  }
}

void FixDefSteps() {
  interval = 10;
  timeDelay = 5000;
  stepDistance = stepper.setStepFrac(8, stepAngle, acmeLead);
  printWords(9, 1, 30, 19, 0x64df, "Initialization");
  // digitalWrite(dirPin, LOW);
  ads.linearCal(low_cal_ADC, high_cal_ADC, low_cal_sel, high_cal_sel);
  float fastForce = ads.measure(txdx1);
  currentMillis = millis() - startMillis;
  currentTime = (currentMillis / 1000.00);
  if (counter <= stepsDeform) {
    stepper.move(1, timeDelay, 1);
    // digitalWrite(stepPin, HIGH);
    count++;
    counter++;
    // digitalWrite(stepPin, LOW);
    distCounter++;
    tracker += stepDistance;
    hiLow();
    Serial.print(currentTime);
    Serial.print(", ");
    Serial.print(count);
    Serial.print(", ");
    Serial.print(tracker, 4);
    Serial.print(", ");
    Serial.print(cycles);
    Serial.print(", ");
    Serial.println(fastForce, 2);
    previousMillis = currentMillis;
    if (counter > stepsDeform) {
      cycleCount++;
      counter = 0;
      interval = 10;
      timeDelay = fpsDelay;
      runState = 0;
    }
  }
}

int forceHighADC() {
  int firstADC = 0;
  int avgHigh;
  uint8_t i;
  int samplesHigh[NUMSAMPLES];
  while (digitalRead(enSW)) {
    for (i = 0; i < NUMSAMPLES; i++) {
      samplesHigh[i] = ads.readADC_Differential_0_1();
      delay(1);
    }
    avgHigh = 0;
    for (i = 0; i < NUMSAMPLES; i++) {
      avgHigh += samplesHigh[i];
    }
    avgHigh /= NUMSAMPLES;
    firstADC = avgHigh;
    printNumber(2, 90, 66, ST77XX_WHITE, ST77XX_BLACK, firstADC);
    delay(200);
  }
  while (digitalRead(enSW) == 0) {
    high_cal_ADC = firstADC;
  }
  return high_cal_ADC;
}

float forceHighSel() {
  encoderPos = CAL_FORCE_MAX;
  while (digitalRead(enSW)) {
    char buffer[10];
    sprintf(buffer, "%d ", encoderPos);
    printWords(0, 2, 102, 86, ST77XX_WHITE, buffer);
    high_cal_sel = encoderPos * 9.81;
  }
  while (digitalRead(enSW) == 0) {
  }
  highSel.write(high_cal_sel);
  return high_cal_sel;
}

int forceLowADC() {
  calWords();
  int firstADC = 0;
  int avgLow;
  uint8_t i;
  int samplesLow[NUMSAMPLES];
  while (digitalRead(enSW)) {
    for (i = 0; i < NUMSAMPLES; i++) {
      samplesLow[i] = ads.readADC_Differential_0_1();
      delay(1);
    }
    avgLow = 0;
    for (i = 0; i < NUMSAMPLES; i++) {
      avgLow += samplesLow[i];
    }
    avgLow /= NUMSAMPLES;
    firstADC = avgLow;
    printNumber(2, 90, 26, ST77XX_WHITE, ST77XX_BLACK, firstADC);
    delay(200);
  }
  while (digitalRead(enSW) == 0) {
    low_cal_ADC = firstADC;
  }
  return low_cal_ADC;
}

float forceLowSel() {
  encoderPos = CAL_FORCE_MIN;
  while (digitalRead(enSW)) {
    char buffer[10];
    sprintf(buffer, "%d ", encoderPos);
    printWords(0, 2, 102, 46, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    low_cal_sel = encoderPos;
  }
  lowSel.write(low_cal_sel);
  return low_cal_sel;
}

void header() {
  int i;
  Serial.print("Preload (mm) = ");
  Serial.println(preload, 4);
  Serial.print("Deform (mm) = ");
  Serial.println(deform, 4);
  Serial.print("Deform (%) = ");
  Serial.println(dfrm);
  Serial.print("Steps (#) = ");
  Serial.println(stepsDeform);
  Serial.print("Rate Fwd (mm/sec) = ");
  Serial.println(rateFwd, 4);
  Serial.print("Rate Rev (mm/sec) = ");
  Serial.println(rateRev, 4);
  Serial.print("Cycles (#) = ");
  Serial.println(numCycles);
  Serial.print("Time");
  Serial.print(",");
  Serial.print("Frame");
  Serial.print(",");
  Serial.print("Distance");
  Serial.print(",");
  Serial.print("Cycle");
  Serial.print(",");
  Serial.println("Force");
  // while (i < (5*fps)) {
  //   averaging(NUMSAMPLES);
  //   Serial.print("Pre");
  //   Serial.print(", , , , ");
  //   Serial.println(avg, 3);
  //   delay(timeDelay);
  //   i++;
  // }
  PrintHeader = false;
}

void hiLow() {
  int now = interval;
  while (now--) {
    digitalWrite(CamTrig, HIGH);
  }
  digitalWrite(CamTrig, LOW);
}

void homing() {
  RevGapTime = 1000 / (1 / stepDistance);
  currentTimer = millis();
  // digitalWrite(dirPin, HIGH);
  if ((tracker - preload) > 0) {
    tracker = tracker - stepDistance;
    stepper.move(1, RevGapTime, -1);
    // digitalWrite(stepPin, HIGH);
    // digitalWrite(stepPin, LOW);
    previousTimer = currentTimer;
  }
  if (tracker - preload == 0) {
    // digitalWrite(dirPin, LOW);
    home = false;
  }
}

void initScreen() {
  printWords(9, 1, 30, 19, 0x64df, "Initialization");
  tft.drawFastHLine(2, 24, 158, 0xfe31);
  printWords(9, 1, 2, 39, 0x04d3, "Calib:");
  tft.drawFastHLine(2, 44, 158, 0xfe31);
  printWords(9, 1, 2, 59, 0x04d3, "Lights:");
  tft.drawFastHLine(2, 64, 158, 0xfe31);
  printWords(9, 1, 2, 79, 0x04d3, "Zero:");
  tft.drawFastHLine(2, 84, 158, 0xfe31);
  printWords(9, 1, 2, 99, 0x04d3, "Preload:");
  tft.drawFastHLine(2, 104, 158, 0xfe31);
  printWords(9, 1, 2, 119, 0x04d3, "Type:");
}

void lighting() {
  const char *myString[] = { "On", "Off" };
  encoderPos = 0;
  while (digitalRead(enSW)) {
    if (encoderPos > 1) {
      encoderPos = 1;
    }
    if (encoderPos < 0) {
      encoderPos = 0;
    }
    int colorChoice = encoderPos;
    if (colorChoice == 0) {
      listBox(80, 46, 80, 14, ST77XX_BLACK);
      printWords(9, 1, 80, 59, ST77XX_WHITE, myString[colorChoice]);
      digitalWrite(ledPin, HIGH);
      choice = colorChoice;
    } else if (colorChoice == 1) {
      listBox(80, 46, 80, 14, ST77XX_BLACK);
      printWords(9, 1, 80, 59, ST77XX_WHITE, myString[colorChoice]);
      digitalWrite(ledPin, LOW);
      choice = colorChoice;
    }
  }
  while (digitalRead(enSW) == 0) {
    printWords(9, 1, 80, 59, 0xfb2c, myString[choice]);
  }
}

void listBox(uint8_t posX, uint8_t posY, uint8_t wide, uint8_t high, uint16_t fontColor) {
  if (box == true) {
    tft.fillRect(posX, posY, wide, high, fontColor);
    box = false;
  }
}

void offset() {
  double samplesOffset[NUMSAMPLES];
  double avgSample;
  uint8_t i;
  double tempAvg;
  encoderPos = 0;
  int tempLowADC = low_cal_ADC;
  int tempHighADC = high_cal_ADC;
  while (digitalRead(enSW)) {
    tempLowADC = (low_cal_ADC - (encoderPos * 10));
    tempHighADC = (high_cal_ADC - (encoderPos * 10));
    for (i = 0; i < NUMSAMPLES; i++) {
      ads.linearCal(tempLowADC, tempHighADC, low_cal_sel, high_cal_sel);
      samplesOffset[i] = ads.measure(txdx1);
      delay(10);
    }
    avgSample = 0;
    for (i = 0; i < NUMSAMPLES; i++) {
      avgSample += samplesOffset[i];
    }
    avgSample /= NUMSAMPLES;
    tempAvg = avgSample;
    char tempOffset[10];
    sprintf(tempOffset, "%.1f ", tempAvg);
    printWords(0, 2, 90, 106, ST77XX_WHITE, tempOffset);
  }
  while (digitalRead(enSW) == 0) {
    low_cal_ADC = tempLowADC;
    high_cal_ADC = tempHighADC;
  }
  highADC.write(tempHighADC);
}

void printWords(byte font, int fontSize, int posX, int posY, uint16_t fontColor, const char *words) {
  if (font == 9) {
    tft.setFont(&FreeSansBold9pt7b);
  } else if (font == 7) {
    tft.setFont(&FreeSansBold7pt7b);
  } else if (font == 8) {
    tft.setFont(&FreeSansBold8pt7b);
  } else if (font == 0) {
    tft.setFont();
  }
  tft.setTextSize(fontSize);
  tft.setCursor(posX, posY);
  tft.setTextColor(fontColor, ST77XX_BLACK);
  tft.print(words);
}

void printNumber(int fontSize, int posX, int posY, uint16_t fontColor, uint16_t fontBkg, double num) {
  tft.setFont();
  tft.setTextSize(fontSize);
  tft.setTextColor(fontColor, fontBkg);
  tft.setCursor(posX, posY);
  dtostrf(num, 6, 1, number);
  tft.print(number);
}

void rowNames() {
  printWords(9, 1, 2, 19, 0x64df, "Force");
  tft.drawFastHLine(2, 25, 158, 0xfe31);
  printWords(9, 1, 2, 44, 0x64df, "Length");
  tft.drawFastHLine(2, 52, 158, 0xfe31);
  printWords(9, 1, 2, 70, 0x64df, "Time");
  tft.drawFastHLine(2, 79, 158, 0xfe31);
  printWords(9, 1, 2, 96, 0x64df, "Cycle");
}

void precondition() {
  char buffer1[7];
  char buffer2[7];
  char buffer3[4];
  char buffer4[3];
  tft.fillScreen(ST77XX_BLACK);
  encoderPos = 0;
  rateFwd = 0.01;
  rateRev = 0.01;
  dfrm = 10;
  deform = preload * 0.1;
  numCycles = 10;
  int tempCycles = 10;
  stepsDeform = deform / stepDistance;
  printWords(9, 1, 14, 19, 0x64df, "Preconditioning");
  tft.drawFastHLine(2, 24, 158, 0xfe31);
  printWords(9, 1, 2, 39, 0x04d3, "Rate Fwd:");
  sprintf(buffer1, "%.3f ", rateFwd);
  printWords(0, 2, 90, 27, 0xfb2c, buffer1);
  tft.drawFastHLine(2, 44, 158, 0xfe31);
  printWords(9, 1, 2, 58, 0x04d3, "Rate Rev:");
  sprintf(buffer2, "%.3f ", rateRev);
  printWords(0, 2, 90, 47, 0xfb2c, buffer2);
  tft.drawFastHLine(2, 64, 158, 0xfe31);
  printWords(9, 1, 2, 79, 0x04d3, "Deform:");
  tft.drawFastHLine(2, 84, 158, 0xfe31);
  sprintf(buffer3, "%u%% ", dfrm);
  printWords(0, 2, 90, 68, 0xfb2c, buffer3);
  printWords(9, 1, 2, 98, 0x04d3, "# Cyles:");
  sprintf(buffer4, "%u ", tempCycles);
  printWords(0, 2, 90, 88, 0xfb2c, buffer4);
  tft.drawFastHLine(2, 104, 158, 0xfe31);
}

void preloading() {
  stepDistance = stepper.setStepFrac(8, stepAngle, acmeLead);
  // digitalWrite(enPin, LOW);
  selPreload = preload;
  encoderPos = 0;
  char buffer[7];
  char buffer2[7];
  while (digitalRead(enSW)) {
    int posPreload = encoderPos;
    averaging(NUMSAMPLES);
    delay(100);
    preload = selPreload + (encoderPos * stepDistance);
    // tracker = preload;
    sprintf(buffer, "%.3f ", preload);
    sprintf(buffer2, "%.2f ", avg);
    printWords(0, 2, 80, 87, ST77XX_WHITE, buffer);
    printWords(0, 2, 80, 106, ST77XX_WHITE, buffer2);
    if (posPreload > encoderPos) {
      stepper.move(1, 2, -1);
    } else if (posPreload < encoderPos) {
      stepper.move(1, 2, 1);
    }
    posPreload = encoderPos;
  }
  while (digitalRead(enSW) == 0) {
    tracker = preload;
    delay(100);
    printWords(0, 2, 80, 87, 0xfb2c, buffer);
    printWords(0, 2, 80, 106, ST77XX_BLACK, buffer2);
  }
}

void testType() {
  encoderPos = 0;
  const char *myMenu[] = { "Precon", "Velocity", "Step", "Strain" };
  int type = encoderPos;
  while (digitalRead(enSW)) {
    if (encoderPos < 0) { encoderPos = 0; }
    if (encoderPos > 3) { encoderPos = 3; }
    int type = encoderPos;
    if (type == 0) {
      listBox(79, 105, 80, 23, ST77XX_BLACK);
      printWords(9, 1, 80, 118, ST77XX_WHITE, myMenu[type]);
      expType = type;
    }
    if (type == 1) {
      listBox(79, 105, 80, 20, ST77XX_BLACK);
      printWords(9, 1, 80, 118, ST77XX_WHITE, myMenu[type]);
      expType = type;
    }
    if (type == 2) {
      listBox(79, 105, 80, 20, ST77XX_BLACK);
      printWords(9, 1, 80, 118, ST77XX_WHITE, myMenu[type]);
      expType = type;
    }
    if (type == 3) {
      listBox(79, 105, 80, 20, ST77XX_BLACK);
      printWords(9, 1, 80, 118, ST77XX_WHITE, myMenu[type]);
      expType = type;
    }
  }
  while (digitalRead(enSW) == 0) {
    printWords(9, 1, 80, 118, 0xfb2c, myMenu[expType]);
  }
  if (expType == 0) {
    Serial.println("Preconditioning");
    precondition();
  }
  if (expType == 1) {
    constVelocity();
    Serial.println("Constant Velocity");
  }
  if (expType == 2) {
    Serial.println("Stress Relaxation");
    Steps();
  }
  if (expType == 3) {
    Serial.println("Constant Tension");
    TensionSel();
  }
}

void Steps() {
  tft.fillScreen(ST77XX_BLACK);
  encoderPos = 0;
  printWords(9, 1, 4, 19, 0x64df, "Step Deformation");
  tft.drawFastHLine(2, 24, 158, 0xfe31);
  printWords(9, 1, 2, 39, 0x04d3, "Rate Fwd:");
  printWords(9, 1, 90, 39, 0xfb2c, "High");
  tft.drawFastHLine(2, 46, 158, 0xfe31);
  printWords(9, 1, 2, 61, 0x04d3, "Rate Rev:");
  printWords(9, 1, 90, 61, 0xfb2c, "None");
  tft.drawFastHLine(2, 64, 158, 0xfe31);
  printWords(9, 1, 2, 82, 0x04d3, "Deform:");
  tft.drawFastHLine(2, 85, 158, 0xfe31);
  SelDeform();
  step = 1;
  // rateFwd = 1.000;
}

void SelDeform() {
  char buffer[4];
  encoderPos = 40;
  while (digitalRead(enSW)) {
    if (encoderPos < 0) {
      encoderPos = 0;
    }
    dfrm = encoderPos;
    sprintf(buffer, "%u%% ", dfrm);
    printWords(0, 2, 90, 68, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    printWords(0, 2, 90, 68, 0xfb2c, buffer);
    deform = preload * (dfrm * 0.01);
    stepsDeform = deform / stepDistance;
  }
}

void SelNumCycles() {
  char buffer[3];
  encoderPos = 0;
  while (digitalRead(enSW)) {
    if (encoderPos < 0) {
      encoderPos = 0;
    }
    sprintf(buffer, "%u ", encoderPos);
    printWords(0, 2, 90, 88, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    printWords(0, 2, 90, 88, 0xfb2c, buffer);
    numCycles = encoderPos;
    if (numCycles == 0) {
      SelNumCycles();
    }
  }
}

void SelRateFwd() {
  char buffer[7];
  float rate;
  encoderPos = 20;
  while (digitalRead(enSW)) {
    if (encoderPos < 0) {
      encoderPos = 0;
    }
    rate = 0.005 * encoderPos;
    sprintf(buffer, "%.3f ", rate);
    printWords(0, 2, 90, 27, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    printWords(0, 2, 90, 27, 0xfb2c, buffer);
    if (rate <= 10.000) {
      rateFwd = rate;
    } else {
      rateFwd = 10.000;
    }
  }
}

void SelRateRev() {
  char buffer[7];
  float rate = rateFwd;
  while (digitalRead(enSW)) {
    if (encoderPos < 0) {
      encoderPos = 0;
    }
    rate = 0.005 * encoderPos;
    sprintf(buffer, "%.3f ", rate);
    printWords(0, 2, 90, 47, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    printWords(0, 2, 90, 47, 0xfb2c, buffer);
    if (rate <= 10.000) {
      rateRev = rate;
    } else {
      rateRev = 10.000;
    }
  }
}

void strain() {
  stepper.setStepFrac(16, stepAngle, acmeLead);
  averaging(NUMSAMPLES);
  float tensionDiff = 0.00;
  tensionDiff = (conTension - avg);
  if (tensionDiff <= -5) {
    stepper.move(1, 5, -1);
    tracker += stepDistance;
  } else if (tensionDiff >= 5) {
    stepper.move(1, 5, 1);
    tracker -= stepDistance;
  } else {
  stepper.move(0, 5, -1);
  }
}

void switchCount() {
  count = 0;
  cycleCount = 0;
  dtostrf(cycleCount, 3, 0, cycles);
  printWords(0, 2, 100, 83, ST77XX_RED, cycles);
}

void switchPos() {
  tft.fillRect(1, 109, 159, 18, ST77XX_BLACK);
}

void TensionSel() {
  tft.fillScreen(ST77XX_BLACK);
  encoderPos = 0;
  printWords(9, 1, 4, 19, 0x64df, "Constant Strain");
  tft.drawFastHLine(2, 24, 158, 0xfe31);
  printWords(9, 1, 2, 39, 0x04d3, "Strain ");
  printWords(9, 1, 2, 61, 0x04d3, "(in mN)");
  tft.drawFastHLine(2, 64, 158, 0xfe31);
  char buffer[5];
  float ConStrain;
  encoderPos = 0;
  while (digitalRead(enSW)) {
    if (encoderPos < 0) {
      encoderPos = 0;
    }
    ConStrain = encoderPos;
    sprintf(buffer, "%.1f ", ConStrain);
    printWords(0, 2, 90, 27, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    printWords(0, 2, 90, 27, 0xfb2c, buffer);
    if (ConStrain <= 20.0) {
      conTension = ConStrain;
    } else {
      conTension = 20.0;
    }
  }
  step = 2;
}

void ZeroChoice() {
  const char *zero[] = { "No", "Yes" };
  encoderPos = 0;
  while (digitalRead(enSW)) {
    int position = encoderPos;
    if (position < 0) { position = 0; }
    if (position > 1) { position = 1; }
    if (position == 0) {
      listBox(80, 66, 80, 14, ST77XX_BLACK);
      printWords(9, 1, 80, 79, ST77XX_WHITE, zero[position]);
      zeroing = position;
    }
    if (position == 1) {
      listBox(80, 66, 80, 14, ST77XX_BLACK);
      printWords(9, 1, 80, 79, ST77XX_WHITE, zero[position]);
      zeroing = position;
    }
  }
  while (digitalRead(enSW) == 0) {
    printWords(9, 1, 80, 79, 0xfb2c, zero[zeroing]);
  }
  if (zeroing == 0) {
    // preload = saveLoad.read();
    preload = 4.49;
  }
  if (zeroing == 1) {
    ZeroSelect();
    autoloading();
  }
}

double zeroForce() {
  double zeroOffset[NUMSAMPLES];
  double avgSample;
  double zeroAvg;
  uint8_t i;
  for (i = 0; i < NUMSAMPLES; i++) {
    ads.linearCal(low_cal_ADC, high_cal_ADC, low_cal_sel, high_cal_sel);
    zeroOffset[i] = ads.measure(txdx1);
    delay(10);
  }
  avgSample = 0;
    for (i = 0; i < NUMSAMPLES; i++) {
    avgSample += zeroOffset[i];
  }
    avgSample /= NUMSAMPLES;
    zeroAvg = avgSample;
    return zeroAvg;
}

void ZeroSelect() {
  char buffer[7];
  int selZero = 0;
  encoderPos = 0;
  stepDistance = stepper.setStepFrac(8, stepAngle, acmeLead);
  while (digitalRead(enSW)) {
    avg = zeroForce();
    if (selZero > encoderPos) {
      stepper.move(1, 5, -1);
      selZero = encoderPos;
    }
    if (selZero < encoderPos) {
      stepper.move(1, 5, 1);
      selZero = encoderPos;
    }
    sprintf(buffer, "%.2f ", avg);
    printWords(0, 2, 80, 106, ST77XX_WHITE, buffer);
  }
  while (digitalRead(enSW) == 0) {
    tft.fillRect(80, 66, 80, 15, ST77XX_BLACK);
    printWords(9, 1, 80, 79, 0xfb2c, "Zeroed");
    selPreload = 1.300;
  }
}

void recvOneChar() {
 if (Serial.available() > 0) {
 receivedChar = Serial.read();
 newData = true;
 }
}

void showNewData() {
 if (newData == true) {
  if (receivedChar == 'G') {
    listBox(79, 109, 79, 18, ST77XX_BLACK);
    tft.fillScreen(ST7735_BLACK);
    printWords(7, 1, 6, 122, ST77XX_GREEN, "RUNNING");
    tft.drawRect(2, 108, 158, 20, ST77XX_GREEN);
    tft.fillRect(79, 109, 79, 18, ST77XX_BLACK);
    cycleCountTemp = 0;
    PrintHeader = true;
    toggle = 0;
    runState = 0;
    encoderPos = 0;
    box = !box;
  }
  else if (receivedChar == 'S') {
      runState = 1;
      tft.fillScreen(ST7735_BLACK);
      tft.drawRect(2, 108, 158, 20, ST77XX_RED);
      printWords(7, 1, 6, 122, ST77XX_RED, "STOPPED");
      box = !box;
  }
  else if (receivedChar == 'R') {
    tft.fillScreen(ST7735_BLACK);
    rowNames();
    toggle = 0;
    runState = 0;
    UseStartTime = true;
  }
 newData = false;
 }
}

/*******************************Core Functions *******************************/
void isRunning() {
  recvOneChar();
  showNewData();
  const char *myMenu[] = { "PAUSE?", "STEP" };
    if (step == 0) {
    ConstVelCycle();
    if (toggle == 1) {
      dtostrf(cycleCount, 3, 0, cycles);
      printWords(0, 2, 100, 83, ST77XX_WHITE, cycles);
      runState = 1;
    }
  }
  if (step == 1) {
    runState = 2;
  }
  if (step == 2) {
    strain();
  }
  if (UseStartTime == true) {
    startMillis = millis();
    UseStartTime = false;
  }
  currentMillis = millis() - startMillis;
  listBox(79, 109, 79, 18, ST77XX_BLACK);
  if (currentMillis - previousMillis >= timeDelay) {
    currentTime = (currentMillis / 1000.00);
    encoderLimit(0, 1);
    if (encoderPos == 0) {
      listBox(79, 109, 79, 18, ST77XX_BLACK);
      printWords(7, 1, 88, 122, ST77XX_YELLOW, myMenu[encoderPos]);
    }
    if (encoderPos == 1) {
      listBox(79, 109, 79, 18, ST77XX_BLACK);
      printWords(7, 1, 88, 122, ST77XX_YELLOW, myMenu[encoderPos]);
    }
    averaging(NUMSAMPLES);
    cameraFrame++;
    sprintf(time, "%.2f", currentTime);
    sprintf(distTravel, "%.2f", tracker);
    sprintf(force, "%.2f", avg);
    sprintf(cycles, "%d", cycleCount);
    printWords(0, 2, 64, 6, ST77XX_WHITE, force);
    printWords(0, 2, 100, 31, ST77XX_WHITE, distTravel);
    printWords(0, 2, 64, 57, ST77XX_WHITE, time);
    printWords(0, 2, 100, 83, ST77XX_WHITE, cycles);
    if (captureChoice > 0 && cameraFrame == captureChoice) {
      count++;
      hiLow();
      cameraFrame = 0;
    }
    sprintf(serialOutput, "%.2f, %d, %.3f, %d, %.3f", currentTime, count, tracker, cycleCount, avg);
    Serial.println(serialOutput);
    previousMillis = currentMillis;
  }
  while (digitalRead(enSW) == 0) {
    int switchChoice = encoderPos;
    if ((step == 0) && (switchChoice == 0)) {
      runState = 1;
      tft.fillScreen(ST7735_BLACK);
      printWords(7, 1, 6, 122, ST77XX_RED, "STOPPED");
    } else if ((step == 0) && (switchChoice == 1)) {
    } else if ((step == 1) && (switchChoice == 0)) {
      runState = 1;
      tft.fillScreen(ST7735_BLACK);
      printWords(7, 1, 6, 122, ST77XX_RED, "STOPPED");
    } else if ((step == 1) && (switchChoice == 1)) {
      makeStep = true;
    }
    encoderPos = 0;
  }
}

void isStopping() {
  recvOneChar();
  showNewData();
  const char *myMenu[] = { "UNPAUSE", "HOME", "REPEAT", "RESET" };
  if (home == true) {
    homing();
    switchCount();
  }
  currentMillis = millis();
  encoderLimit(0, 3);
  listBox(79, 109, 79, 18, ST77XX_BLACK);
  printWords(7, 1, 88, 122, ST77XX_YELLOW, myMenu[encoderPos]);
  rowNames();
  if (currentMillis - previousMillis >= timeDelay) {
    averaging(NUMSAMPLES);
    sprintf(force, "%.2f", avg);
    sprintf(distTravel, "%.2f", tracker);
    printWords(0, 2, 64, 6, ST77XX_RED, force);
    printWords(0, 2, 100, 31, ST77XX_RED, distTravel);
    printWords(0, 2, 100, 57, ST77XX_RED, "  --- ");
    printWords(0, 2, 100, 83, ST77XX_RED, cycles);
    previousMillis = currentMillis;
  }
  while (digitalRead(enSW) == 0) {
    int switchChoice = encoderPos;
    if (switchChoice == 0) {
      tft.fillRect(79, 109, 79, 18, ST77XX_BLACK);
      cycleCountTemp = 0;
      PrintHeader = true;
      toggle = 0;
      runState = 0;
      tft.fillScreen(ST7735_BLACK);
      printWords(7, 1, 6, 122, ST77XX_GREEN, "RUNNING");
      tft.drawRect(2, 108, 158, 20, ST77XX_GREEN);
      rowNames();
    }
    else if (switchChoice == 1) {
      home = true;
      UseStartTime = true;
      tft.fillRect(79, 109, 79, 18, ST77XX_BLACK);
    }
    else if (switchChoice == 2) {
      toggle = 0;
      runState = 0;
      UseStartTime = true;
      tft.fillScreen(ST7735_BLACK);
      printWords(7, 1, 6, 122, ST77XX_GREEN, "RUNNING");
      tft.drawRect(2, 108, 158, 20, ST77XX_GREEN);
      rowNames();
    }
    else if (switchChoice == 3) {
      NVIC_SystemReset();
    }
  }
}

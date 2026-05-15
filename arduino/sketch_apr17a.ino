#include <Servo.h>

Servo servo1;
Servo servo2;
Servo servo3;
Servo servo4;

void trapeze(Servo &servo, int angleDepart, int angleFin, int dureeMs) {
  int steps = 100;
  float r = angleFin - angleDepart;
  for (int i = 0; i <= steps; i++) {
    float t = (float)i / steps;
    float pos;
    if (t < 1.0/3.0) {
      float t_n = t / (1.0/3.0);
      pos = 0.5 * t_n * t_n * (r / 2.0);
    } else if (t < 2.0/3.0) {
      float t_n = (t - 1.0/3.0) / (1.0/3.0);
      pos = r / 4.0 + t_n * (r / 2.0);
    } else {
      float t_n = (t - 2.0/3.0) / (1.0/3.0);
      pos = r * 3.0/4.0 + (t_n - 0.5 * t_n * t_n) * (r / 2.0);
    }
    servo.write(angleDepart + (int)pos);
    delay(dureeMs / steps);
  }
}

void sequence(int s) {
  int angles[3][2] = {{0, 180}, {0, 90}, {0, 180}};
  int durees[3]    = {3000,     2000,    5000};

  int ad = angles[s][0];
  int af = angles[s][1];
  int d  = durees[s];

  trapeze(servo1, ad, af, d);
  delay(250);
  trapeze(servo2, ad, af, d);
  delay(250);
  trapeze(servo3, ad, af, d);
  delay(250);
  trapeze(servo4, ad, af, d);

  trapeze(servo1, af, ad, d);
  delay(250);
  trapeze(servo2, af, ad, d);
  delay(250);
  trapeze(servo3, af, ad, d);
  delay(250);
  trapeze(servo4, af, ad, d);
}

void setup() {
  Serial.begin(9600);
  servo1.attach(3);
  servo2.attach(6);
  servo3.attach(9);
  servo4.attach(11);
}

void loop() {
  if (Serial.available()) {
    String msg = Serial.readStringUntil('\n');
    if (msg == "SEQ1") sequence(0);
    else if (msg == "SEQ2") sequence(1);
    else if (msg == "SEQ3") sequence(2);
  }
}
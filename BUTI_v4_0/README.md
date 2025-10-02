# BUTI Controller version 4.0
## Biplanar Uniaxial Tension and Imaging System: Now with Software!

This arduino-based code is used to program the BUTI controller.
Paired with [BURST Software](https://github.com/vr-oj/BURST), tension and images can be monitored and controlled without the need for costly interface units.

A few notes:

* While adaptable to other Arduino versions, this code is specifically written to utilize SAMD51-based microcontrollers. The [ItsyBitsy by Adafruit Inc.](https://www.adafruit.com/product/3800) is recommended.
* A myriad of libraries are required in addition to the custom ones included here. All are available directly through the Arduino IDE Library Manager. They include:
  * FlashStorage.h
  * Adafruit_GFX.h (and dependencies)
  * Adafruit_ST7735.h (and dependencies)
  * SPI.h (if not already included natively)
  Code updates cannot be uploaded without the libraries being installed. It's also okay to install library updates when they occur.
* You must add the following "Additional Boards Manager URLs" in youir Arduino IDE preferences:
  * https://raw.githubusercontent.com/MHEtLive/arduino-boards-index/master/package_mhetlive_index.json
  * https://adafruit.github.io/arduino-board-index/package_adafruit_index.json


***Use at your own peril with other microcontrollers. I tried to clearly label what pins should be changed, but it's possible to incinerate your microcontroller if pin assignments are incorrect.***

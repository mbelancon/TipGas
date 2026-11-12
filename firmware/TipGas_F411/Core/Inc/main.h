/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.h
  * @brief          : Header for main.c file.
  ******************************************************************************
  */
/* USER CODE END Header */

#ifndef __MAIN_H
#define __MAIN_H

#ifdef __cplusplus
extern "C" {
#endif

#include "stm32f4xx_hal.h"

/* USER CODE BEGIN Includes */

/* USER CODE END Includes */

void Error_Handler(void);

/* Private defines -----------------------------------------------------------*/
#define LED_Pin GPIO_PIN_13
#define LED_GPIO_Port GPIOC
#define HALL3_Pin GPIO_PIN_2
#define HALL3_GPIO_Port GPIOA
#define HALL3_EXTI_IRQn EXTI2_IRQn
#define HALL4_Pin GPIO_PIN_3
#define HALL4_GPIO_Port GPIOA
#define HALL4_EXTI_IRQn EXTI3_IRQn
#define HALL5_Pin GPIO_PIN_4
#define HALL5_GPIO_Port GPIOA
#define HALL5_EXTI_IRQn EXTI4_IRQn
#define HALL6_Pin GPIO_PIN_5
#define HALL6_GPIO_Port GPIOA
#define HALL6_EXTI_IRQn EXTI9_5_IRQn
#define HALL7_Pin GPIO_PIN_6
#define HALL7_GPIO_Port GPIOA
#define HALL7_EXTI_IRQn EXTI9_5_IRQn
#define HALL8_Pin GPIO_PIN_7
#define HALL8_GPIO_Port GPIOA
#define HALL8_EXTI_IRQn EXTI9_5_IRQn
#define HALL1_Pin GPIO_PIN_0
#define HALL1_GPIO_Port GPIOB
#define HALL1_EXTI_IRQn EXTI0_IRQn
#define HALL2_Pin GPIO_PIN_1
#define HALL2_GPIO_Port GPIOB
#define HALL2_EXTI_IRQn EXTI1_IRQn
#define HALL9_Pin GPIO_PIN_8
#define HALL9_GPIO_Port GPIOA
#define HALL9_EXTI_IRQn EXTI9_5_IRQn
#define ONEWIRE_Pin GPIO_PIN_8
#define ONEWIRE_GPIO_Port GPIOB

/* USER CODE BEGIN Private defines */

/* USER CODE END Private defines */

#ifdef __cplusplus
}
#endif

#endif /* __MAIN_H */

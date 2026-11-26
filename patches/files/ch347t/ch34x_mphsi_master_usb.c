/*
 * USB to SPI/I2C/GPIO controller driver for USB converter chip CH347/CH341/CH339/CH9341, etc.
 *
 * Copyright (C) 2026 Nanjing Qinheng Microelectronics Co., Ltd.
 * Web: http://wch.cn
 * Author: WCH <tech@wch.cn>
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 2 of the License, or
 * (at your option) any later version.
 *
 * Update Log:
 * V1.0 - initial version
 * V1.1 - add supports for i2c controller, gpio irq function
 * V1.2 - add supports for i2c communication of long packets, use workqueue to implement irq setting operation,
 *      - support more spi clock frequency
 * V1.3 - add supports for gpio level triggered interrupt, add mutex in ch347_spi_transfer_one_message
 * V1.4 - fix the big-endian CPU compatibility issue during SPI configuration
 *      - fix the problem that obtaining GPIO status will change GPIO configuration
 * V1.5 - enable I2C function for CH347F automatically
 *      - fix ch34x_i2c_check_dev function of CH341
 * V1.6 - add support for kernel version beyond 6.8.x
 * V1.7 - add support for CH9341
 */

#include "ch34x_mphsi.h"

static DEFINE_IDA(ch34x_devid_ida);

/* Table of devices that work with this driver */
static const struct usb_device_id ch34x_usb_ids[] = {
	/* ColorOS gateway: do not claim any other WCH model or the UART. */
	{ USB_DEVICE_INTERFACE_NUMBER(0x1a86, 0x55db, 0x02) },
	{} /* Terminating entry */
};

MODULE_DEVICE_TABLE(usb, ch34x_usb_ids);

struct ch341_pin_config ch341_board_config[CH341_CS_NUM] = {
	{ 15, "cs0" },
	{ 16, "cs1" },
	{ 17, "cs2" },
};

struct ch34x_pin_config ch347t_board_config[CH347T_MPHSI_GPIOS] = {
	{ 15, "GPIO4", 4, GPIO_MODE_OUT, true },
	{ 2, "GPIO6", 6, GPIO_MODE_IN, true },
	{ 13, "GPIO7", 7, GPIO_MODE_OUT, true },
};

struct ch34x_pin_config ch347f_board_config[CH347F_MPHSI_GPIOS] = {
	{ 17, NULL, 0, GPIO_MODE_IN, true },
	{ 18, NULL, 1, GPIO_MODE_OUT, true },
	{ 10, NULL, 2, GPIO_MODE_OUT, true },
	{ 9, NULL, 3, GPIO_MODE_OUT, true },
	{ 23, NULL, 4, GPIO_MODE_OUT, true },
	{ 24, NULL, 5, GPIO_MODE_IN, true },
	{ 25, NULL, 6, GPIO_MODE_OUT, true },
	{ 26, NULL, 7, GPIO_MODE_OUT, true },
};

struct ch34x_pin_config ch9341c_board_config[CH9341C_MPHSI_GPIOS] = {
	{ 17, NULL, 0, GPIO_MODE_IN, true },
	{ 18, NULL, 1, GPIO_MODE_IN, true },
	{ 10, NULL, 2, GPIO_MODE_IN, true },
	{ 9, NULL, 3, GPIO_MODE_IN, false },
	{ 23, NULL, 4, GPIO_MODE_IN, false },
	{ 24, NULL, 5, GPIO_MODE_IN, false },
	{ 25, NULL, 6, GPIO_MODE_IN, false },
	{ 26, NULL, 7, GPIO_MODE_IN, true },
	{ 26, NULL, 8, GPIO_MODE_IN, true },
	{ 26, NULL, 9, GPIO_MODE_IN, true },
};

struct ch34x_pin_config ch339w_board_config[CH339W_MPHSI_GPIOS] = {
	{ 59, NULL, 1, GPIO_MODE_OUT, false },
	{ 37, NULL, 2, GPIO_MODE_OUT, false },
	{ 36, NULL, 3, GPIO_MODE_OUT, false },
};

extern int ch34x_spi_probe(struct ch34x_device *ch34x_dev);
extern void ch34x_spi_remove(struct ch34x_device *ch34x_dev);
extern int ch34x_irq_probe(struct ch34x_device *ch34x_dev);
extern void ch34x_irq_remove(struct ch34x_device *ch34x_dev);
extern int ch34x_mphsi_gpio_probe(struct ch34x_device *ch34x_dev);
extern void ch34x_mphsi_gpio_remove(struct ch34x_device *ch34x_dev);
extern int ch34x_irq_check(struct ch34x_device *ch34x_dev, u8 irq);
extern int ch34x_usb_transfer(struct ch34x_device *ch34x_dev, u8 ch,
			      int out_len, int in_len);
extern bool ch347_get_chipinfo(struct ch34x_device *ch34x_dev);
extern bool ch347_func_switch(struct ch34x_device *ch34x_dev, int index);

static int ch34x_cfg_probe(struct ch34x_device *ch34x_dev)
{
	struct ch34x_pin_config *ch34xcfg;
	int i;

	CHECK_PARAM_RET(ch34x_dev, -EINVAL);

	if (ch34x_dev->chiptype == CHIP_CH341) {
		/* Setting out: mosi/out2/sck/cs, in: miso */
		ch34x_dev->gpio_mask = 0x3f;
		ch34x_dev->slave_num = CH341_CS_NUM;
	} else if (ch34x_dev->chiptype == CHIP_CH347F ||
		   ch34x_dev->chiptype == CHIP_CH347T) {
		if ((ch34x_dev->chiptype == CHIP_CH347T &&
		     ch34x_dev->firmver >= 0x0341) ||
		    (ch34x_dev->chiptype == CHIP_CH347F)) {
			ch34x_dev->irq_num = 0;
			ch34x_dev->irq_base = 0;
		}
		ch34x_dev->slave_num = CH347_CS_NUM;

		if (ch34x_dev->chiptype == CHIP_CH347T) {
			for (i = 0; i < CH347T_MPHSI_GPIOS; i++) {
				ch34xcfg = ch347t_board_config + i;
				ch34x_dev->gpio_names[ch34x_dev->gpio_num] =
					ch34xcfg->name;
				ch34x_dev->gpio_pins[ch34x_dev->gpio_num] =
					ch34xcfg;
				if (ch34x_dev->firmver >= 0x0341) {
					ch34x_dev->gpio_irq_map
						[ch34x_dev->gpio_num] =
						ch34x_dev->irq_num;
					ch34x_dev->irq_gpio_map
						[ch34x_dev->irq_num] =
						ch34x_dev->gpio_num;
					DEV_DBG(CH34X_USBDEV,
						"%s gpio%d irq=%d %s",
						ch34xcfg->mode ==
								GPIO_MODE_IN ?
							"input " :
							"output",
						ch34xcfg->gpioindex,
						ch34x_dev->irq_num,
						ch34xcfg->hwirq ?
							"(hwirq)" :
							"");
					ch34x_dev->irq_num++;
				} else
					DEV_DBG(CH34X_USBDEV, "%s gpio%d",
						ch34xcfg->mode ==
								GPIO_MODE_IN ?
							"input " :
							"output",
						ch34xcfg->gpioindex);

				ch34x_dev->gpio_num++;
			}
		} else {
			for (i = 0; i < CH347F_MPHSI_GPIOS; i++) {
				ch34xcfg = ch347f_board_config + i;
				ch34x_dev->gpio_names[ch34x_dev->gpio_num] =
					ch34xcfg->name;
				ch34x_dev->gpio_pins[ch34x_dev->gpio_num] =
					ch34xcfg;
				ch34x_dev
					->gpio_irq_map[ch34x_dev->gpio_num] =
					ch34x_dev->irq_num;
				ch34x_dev->irq_gpio_map[ch34x_dev->irq_num] =
					ch34x_dev->gpio_num;
				DEV_DBG(CH34X_USBDEV, "%s %d irq=%d %s",
					ch34xcfg->mode == GPIO_MODE_IN ?
						"input " :
						"output",
					ch34xcfg->gpioindex,
					ch34x_dev->irq_num,
					ch34xcfg->hwirq ? "(hwirq)" : "");
				ch34x_dev->irq_num++;
				ch34x_dev->gpio_num++;
			}
		}
	} else if (ch34x_dev->chiptype == CHIP_CH339W) {
		ch34x_dev->slave_num = CH339_CS_NUM;
		if (ch34x_dev->chiptype == CHIP_CH339W) {
			for (i = 0; i < CH339W_MPHSI_GPIOS; i++) {
				ch34xcfg = ch339w_board_config + i;
				ch34x_dev->gpio_names[ch34x_dev->gpio_num] =
					ch34xcfg->name;
				ch34x_dev->gpio_pins[ch34x_dev->gpio_num] =
					ch34xcfg;
				DEV_DBG(CH34X_USBDEV, "%s gpio%d",
					ch34xcfg->mode == GPIO_MODE_IN ?
						"input " :
						"output",
					ch34xcfg->gpioindex);
				ch34x_dev->gpio_num++;
			}
		}
	} else if (ch34x_dev->chiptype == CHIP_CH9341C) {
		ch34x_dev->irq_num = 0;
		ch34x_dev->irq_base = 0;
		ch34x_dev->slave_num = CH9341_CS_NUM;

		for (i = 0; i < CH9341C_MPHSI_GPIOS; i++) {
			ch34xcfg = ch9341c_board_config + i;
			ch34x_dev->gpio_names[ch34x_dev->gpio_num] =
				ch34xcfg->name;
			ch34x_dev->gpio_pins[ch34x_dev->gpio_num] =
				ch34xcfg;
			ch34x_dev->gpio_irq_map[ch34x_dev->gpio_num] =
				ch34x_dev->irq_num;
			ch34x_dev->irq_gpio_map[ch34x_dev->irq_num] =
				ch34x_dev->gpio_num;
			DEV_DBG(CH34X_USBDEV, "%s %d irq=%d %s",
				ch34xcfg->mode == GPIO_MODE_IN ? "input " :
								 "output",
				ch34xcfg->gpioindex, ch34x_dev->irq_num,
				ch34xcfg->hwirq ? "(hwirq)" : "");
			ch34x_dev->irq_num++;
			ch34x_dev->gpio_num++;
		}
	}

	return 0;
}

static void ch34x_cfg_remove(struct ch34x_device *ch34x_dev)
{
	CHECK_PARAM(ch34x_dev);

	return;
}

static int ch34x_wb_alloc(struct ch34x_device *ch34x_dev)
{
	int i, wbn;
	struct ch34x_wb *wb;

	wbn = 0;
	i = 0;
	for (;;) {
		wb = &ch34x_dev->wb[wbn];
		if (!wb->use) {
			wb->use = 1;
			return wbn;
		}
		wbn = (wbn + 1) % CH34X_NW;
		if (++i >= CH34X_NW)
			return -1;
	}
}

static int ch34x_wb_is_avail(struct ch34x_device *ch34x_dev)
{
	int i, n;
	unsigned long flags;

	n = CH34X_NW;
	spin_lock_irqsave(&ch34x_dev->write_lock, flags);
	for (i = 0; i < CH34X_NW; i++)
		n -= ch34x_dev->wb[i].use;
	spin_unlock_irqrestore(&ch34x_dev->write_lock, flags);

	return n;
}

static void ch34x_write_done(struct ch34x_device *ch34x_dev,
			     struct ch34x_wb *wb)
{
	wb->use = 0;
	ch34x_dev->transmitting--;
}

static int ch34x_start_wb(struct ch34x_device *ch34x_dev,
			  struct ch34x_wb *wb)
{
	int rc;

	ch34x_dev->transmitting++;

	wb->urb->transfer_buffer = wb->buf;
	wb->urb->transfer_dma = wb->dmah;
	wb->urb->transfer_buffer_length = wb->len;
	wb->urb->dev = ch34x_dev->usb_dev;

	rc = usb_submit_urb(wb->urb, GFP_ATOMIC);
	if (rc < 0) {
		DEV_ERR(CH34X_USBDEV,
			"%s - usb_submit_urb(write bulk) failed: %d\n",
			__func__, rc);
		ch34x_write_done(ch34x_dev, wb);
	}
	return rc;
}

static void ch34x_write_bulk_callback(struct urb *urb)
{
	struct ch34x_wb *wb = urb->context;
	struct ch34x_device *ch34x_dev = wb->instance;
	unsigned long flags;

	/* sync/async unlink faults aren't errors */
	if (urb->status) {
		if (!(urb->status == -ENOENT ||
		      urb->status == -ECONNRESET ||
		      urb->status == -ESHUTDOWN))
			DEV_ERR(CH34X_USBDEV,
				"%s - Nonzero write bulk status received: %d\n",
				__func__, urb->status);

		spin_lock(&ch34x_dev->err_lock);
		ch34x_dev->errors = urb->status;
		spin_unlock(&ch34x_dev->err_lock);
	}
	spin_lock_irqsave(&ch34x_dev->write_lock, flags);
	ch34x_write_done(ch34x_dev, wb);
	wake_up_interruptible(&ch34x_dev->wq_send);
	spin_unlock_irqrestore(&ch34x_dev->write_lock, flags);
}

int ch34x_usb_transfer(struct ch34x_device *ch34x_dev, u8 ch, int out_len,
		       int in_len)
{
	int retval = 0;
	int actual = 0;
	int rlen;
	int size;
	int wbn;
	struct ch34x_wb *wb;
	unsigned long flags;
	int timeout;
	CHECK_PARAM_RET(ch34x_dev, -EINVAL);

	if (READ_ONCE(ch34x_dev->disconnecting))
		return -ENODEV;
	if (out_len < 0 || out_len > MAX_BUFFER_LENGTH ||
	    in_len < 0 || in_len > MAX_BUFFER_LENGTH ||
	    (out_len && ch >= ch34x_dev->bulkout_num) ||
	    (in_len && ch >= ch34x_dev->bulkin_num))
		return -EINVAL;

	if (out_len != 0) {
retry:
		spin_lock_irqsave(&ch34x_dev->write_lock, flags);
		wbn = ch34x_wb_alloc(ch34x_dev);
		if (wbn < 0) {
			spin_unlock_irqrestore(&ch34x_dev->write_lock,
					       flags);
			timeout = wait_event_interruptible_timeout(
				ch34x_dev->wq_send,
				ch34x_wb_is_avail(ch34x_dev),
				msecs_to_jiffies(DEFAULT_TIMEOUT));
			if (timeout <= 0) {
				return -ETIMEDOUT;
			} else
				goto retry;
		}
		wb = &ch34x_dev->wb[wbn];
		memcpy(wb->buf, ch34x_dev->bulkout_buf, out_len);
		wb->len = out_len;

		if (ch34x_dev->susp_count) {
			spin_unlock_irqrestore(&ch34x_dev->write_lock,
					       flags);
			wb->use = 0;
			return -EIO;
		}

		wb->urb->pipe = usb_sndbulkpipe(
			ch34x_dev->usb_dev,
			ch34x_dev->bulk_out_endpointAddr[ch]);
		retval = ch34x_start_wb(ch34x_dev, wb);
		spin_unlock_irqrestore(&ch34x_dev->write_lock, flags);
		if (retval)
			goto exit;

	}

	if (in_len == 0) {
		actual = out_len;
		goto exit;
	}

	size = in_len;

	memset(ch34x_dev->bulkin_buf, 0, MAX_BUFFER_LENGTH);

	while (actual < size) {
		retval = usb_bulk_msg(
			ch34x_dev->usb_dev,
			usb_rcvbulkpipe(
				ch34x_dev->usb_dev,
				usb_endpoint_num(ch34x_dev->bulk_in[ch])),
			ch34x_dev->bulkin_buf + actual, size - actual,
			&rlen, 2000);
		if (retval) {
			DEV_ERR(CH34X_USBDEV,
				"%s - Failed in usb_bulk_msg, error %d\n",
				__func__, retval);
			break;
		}
		if (!rlen) {
			retval = -EPROTO;
			break;
		}
		actual += rlen;

	}

exit:
	return retval < 0 ? retval : actual;
}

bool ch347_get_chipinfo(struct ch34x_device *ch34x_dev)
{
	u8 *io = ch34x_dev->bulkout_buf;
	int len, i;
	bool ret = false;

	mutex_lock(&ch34x_dev->io_mutex);
	i = 0;
	io[i++] = USB20_CMD_INFO_RD;
	io[i++] = 1;
	io[i++] = 0;
	io[i++] = 0;
	len = i;

	if (ch34x_usb_transfer(ch34x_dev, CH_ALL, len, 0) != len)
		goto exit;

	len = 4 + USB20_CMD_HEADER;

	if (ch34x_usb_transfer(ch34x_dev, CH_ALL, 0, len) != len)
		goto exit;

	if (ch34x_dev->bulkin_buf[0] != USB20_CMD_INFO_RD)
		goto exit;

	ch34x_dev->firmver = (ch34x_dev->bulkin_buf[4] << 8) |
			     ch34x_dev->bulkin_buf[3];
	ret = true;

exit:
	mutex_unlock(&ch34x_dev->io_mutex);
	return ret;
}

bool ch347_func_switch(struct ch34x_device *ch34x_dev, int index)
{
	u8 *io = ch34x_dev->bulkout_buf;
	int len, i;
	bool ret = false;

	memset(io, 0x00, USB20_CMD_HEADER + 8);

	mutex_lock(&ch34x_dev->io_mutex);
	i = 0;
	io[i++] = USB20_CMD_FUNC_SWITCH;
	io[i++] = 8;
	io[i++] = 0;
	switch (index) {
	case 0:
		io[USB20_CMD_HEADER] = 0x81;
		break;
	case 1:
		io[USB20_CMD_HEADER + 1] = 0x81;
		break;
	case 2:
		io[USB20_CMD_HEADER + 1] = 0x82;
		break;
	case 3:
		io[USB20_CMD_HEADER + 2] = 0x81;
		io[USB20_CMD_HEADER + 3] = 0x81;
		break;
	case 4:
		io[USB20_CMD_HEADER] = 0x81;
		io[USB20_CMD_HEADER + 2] = 0x81;
		io[USB20_CMD_HEADER + 3] = 0x81;
		break;
	default:
		break;
	}
	len = USB20_CMD_HEADER + 8;

	if (ch34x_usb_transfer(ch34x_dev, CH_ALL, len, 0) != len)
		goto exit;

	len = 4;

	if (ch34x_usb_transfer(ch34x_dev, CH_ALL, 0, len) != len)
		goto exit;

	if ((ch34x_dev->bulkin_buf[0] != USB20_CMD_FUNC_SWITCH) ||
	    (ch34x_dev->bulkin_buf[USB20_CMD_HEADER] != 0x00))
		goto exit;

	ret = true;

exit:
	mutex_unlock(&ch34x_dev->io_mutex);
	return ret;
}

static void ch34x_usb_complete_intr_urb(struct urb *urb)
{
	struct ch34x_device *ch34x_dev = urb->context;
	int i;

	if (urb->status == -ENOENT || urb->status == -ECONNRESET ||
	    urb->status == -ESHUTDOWN)
		return;

	if (!urb->status) {
		for (i = 0; i < ch34x_dev->irq_num; i++) {
			unsigned int gpio = ch34x_dev->irq_gpio_map[i];
			unsigned int pos = ch34x_dev->gpio_pins[gpio]->gpioindex + 3;

			if (pos < urb->actual_length && (ch34x_dev->intrin_buf[pos] & BIT(3)))
				ch34x_irq_check(ch34x_dev, i);
		}
	}

	if (!READ_ONCE(ch34x_dev->disconnecting))
		usb_submit_urb(urb, GFP_ATOMIC);
}

static int ch34x_write_buffers_alloc(struct ch34x_device *ch34x_dev)
{
	int i;
	struct ch34x_wb *wb;

	for (wb = &ch34x_dev->wb[0], i = 0; i < CH34X_NW; i++, wb++) {
		wb->buf = usb_alloc_coherent(ch34x_dev->usb_dev,
					     ch34x_dev->writesize,
					     GFP_KERNEL, &wb->dmah);
		if (!wb->buf)
			return -ENOMEM;
		/* The single probe teardown path owns all allocated buffers. */
	}
	return 0;
}

static void ch34x_write_buffers_free(struct ch34x_device *ch34x_dev)
{
	int i;
	struct ch34x_wb *wb;

	for (wb = &ch34x_dev->wb[0], i = 0; i < CH34X_NW; i++, wb++) {
		if (wb->buf)
			usb_free_coherent(ch34x_dev->usb_dev,
					  ch34x_dev->writesize, wb->buf,
					  wb->dmah);
	}
}

static void ch34x_usb_free_device(struct ch34x_device *ch34x_dev)
{
	int i;

	CHECK_PARAM(ch34x_dev);

	if (ch34x_dev->bulkout_buf)
		kfree(ch34x_dev->bulkout_buf);
	if (ch34x_dev->bulkin_buf)
		kfree(ch34x_dev->bulkin_buf);
	if (ch34x_dev->intrin_buf)
		kfree(ch34x_dev->intrin_buf);

	if (ch34x_dev->intr_urb)
		usb_free_urb(ch34x_dev->intr_urb);
	for (i = 0; i < CH34X_NW; i++) {
		if (ch34x_dev->wb[i].urb)
			usb_free_urb(ch34x_dev->wb[i].urb);
	}
	ch34x_write_buffers_free(ch34x_dev);
	usb_set_intfdata(ch34x_dev->intf, NULL);
	usb_put_dev(ch34x_dev->usb_dev);
	kfree(ch34x_dev);
}

static void ch34x_draw_down(struct ch34x_device *ch34x_dev);

static int ch34x_usb_probe(struct usb_interface *intf,
			   const struct usb_device_id *id)
{
	struct usb_device *usb_dev =
		usb_get_dev(interface_to_usbdev(intf));
	struct usb_endpoint_descriptor *endpoint;
	struct usb_host_interface *iface_desc;
	struct ch34x_device *ch34x_dev;
	int i, j;
	int ret;
	bool use_irq;


	DEV_DBG(&intf->dev, "Connect device...");

	ch34x_dev = kzalloc(sizeof(struct ch34x_device), GFP_KERNEL);
	if (!ch34x_dev) {
		DEV_ERR(&intf->dev, "Could not allocate device memory");
		usb_put_dev(usb_dev);
		return -ENOMEM;
	}

	ch34x_dev->usb_dev = usb_dev;
	ch34x_dev->intf = intf;
	iface_desc = intf->cur_altsetting;

	DEV_DBG(CH34X_USBDEV, "bNumEndpoints=%d",
		iface_desc->desc.bNumEndpoints);

	for (i = 0; i < iface_desc->desc.bNumEndpoints; i++) {
		endpoint = &iface_desc->endpoint[i].desc;

		DEV_DBG(CH34X_USBDEV,
			"    ->endpoint=%d type=%d dir=%d addr=%0x", i,
			usb_endpoint_type(endpoint),
			usb_endpoint_dir_in(endpoint),
			usb_endpoint_num(endpoint));

		if (usb_endpoint_is_bulk_in(endpoint)) {
			if (ch34x_dev->bulkin_num >= ARRAY_SIZE(ch34x_dev->bulk_in))
				goto bad_endpoints;
			ch34x_dev->bulk_in[ch34x_dev->bulkin_num++] = endpoint;
		} else if (usb_endpoint_is_bulk_out(endpoint)) {
			if (ch34x_dev->bulkout_num >= ARRAY_SIZE(ch34x_dev->bulk_out))
				goto bad_endpoints;
			ch34x_dev->bulk_out[ch34x_dev->bulkout_num] = endpoint;
			ch34x_dev->bulk_out_endpointAddr[ch34x_dev->bulkout_num++] =
				endpoint->bEndpointAddress;
		} else if (usb_endpoint_is_int_in(endpoint)) {
			if (ch34x_dev->intr_in)
				goto bad_endpoints;
			ch34x_dev->intr_in = endpoint;
		}
	}
	if (!ch34x_dev->bulkin_num || !ch34x_dev->bulkout_num)
		goto bad_endpoints;

	ch34x_dev->chiptype = CHIP_CH347T;

	/* Save the pointer to the new ch34x_device in USB interface device data */
	usb_set_intfdata(intf, ch34x_dev);
	mutex_init(&ch34x_dev->io_mutex);
	spin_lock_init(&ch34x_dev->err_lock);
	spin_lock_init(&ch34x_dev->write_lock);
	init_waitqueue_head(&ch34x_dev->wq_send);

	ch34x_dev->bulkin_buf = kmalloc(MAX_BUFFER_LENGTH, GFP_KERNEL);
	if (!ch34x_dev->bulkin_buf) {
		ret = -ENOMEM;
		goto error;
	}

	ch34x_dev->bulkout_buf = kmalloc(MAX_BUFFER_LENGTH, GFP_KERNEL);
	if (!ch34x_dev->bulkout_buf) {
		ret = -ENOMEM;
		goto error;
	}

	ch34x_dev->writesize = MAX_BUFFER_LENGTH;
	ret = ch34x_write_buffers_alloc(ch34x_dev);
	if (ret)
		goto error;

	for (j = 0; j < CH34X_NW; j++) {
		struct ch34x_wb *wb = &(ch34x_dev->wb[j]);

		wb->urb = usb_alloc_urb(0, GFP_KERNEL);
		if (!wb->urb) {
			ret = -ENOMEM;
			goto error;
		}

		usb_fill_bulk_urb(wb->urb, ch34x_dev->usb_dev, 0, NULL,
				  ch34x_dev->writesize,
				  ch34x_write_bulk_callback, wb);
		wb->urb->transfer_flags |= URB_NO_TRANSFER_DMA_MAP;
		wb->instance = ch34x_dev;
	}

	if (!ch347_get_chipinfo(ch34x_dev)) {
		ret = -EPROTO;
		goto error;
	}
	use_irq = ch34x_dev->firmver >= 0x0341 && ch34x_dev->intr_in;
	DEV_DBG(CH34X_USBDEV, "Firmware version: 0x%x.\n", ch34x_dev->firmver);

#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 19, 0)
	ch34x_dev->id = ida_alloc(&ch34x_devid_ida, GFP_KERNEL);
#else
	ch34x_dev->id = ida_simple_get(&ch34x_devid_ida, 0, 0, GFP_KERNEL);
#endif
	if (ch34x_dev->id < 0) {
		ret = ch34x_dev->id;
		goto error;
	}

	ret = ch34x_cfg_probe(ch34x_dev);
	if (ret < 0)
		goto error1;

	if (use_irq) {
		ret = ch34x_irq_probe(ch34x_dev);
		if (ret < 0)
			goto error2;
	} else {
		ch34x_dev->irq_num = 0;
	}

	ret = ch34x_mphsi_gpio_probe(ch34x_dev);
	if (ret < 0)
		goto error3;

	ret = ch34x_spi_probe(ch34x_dev);
	if (ret < 0)
		goto error4;

	if (use_irq) {
		ch34x_dev->intrin_buf = kmalloc(CH347_USB_MAX_INTR_SIZE, GFP_KERNEL);
		ch34x_dev->intr_urb = usb_alloc_urb(0, GFP_KERNEL);
		if (!ch34x_dev->intrin_buf || !ch34x_dev->intr_urb) {
			ret = -ENOMEM;
			goto error5;
		}
		usb_fill_int_urb(ch34x_dev->intr_urb, usb_dev,
				usb_rcvintpipe(usb_dev,
					       usb_endpoint_num(ch34x_dev->intr_in)),
				ch34x_dev->intrin_buf, CH347_USB_MAX_INTR_SIZE,
				ch34x_usb_complete_intr_urb, ch34x_dev,
				ch34x_dev->intr_in->bInterval);
		ret = usb_submit_urb(ch34x_dev->intr_urb, GFP_KERNEL);
		if (ret)
			goto error5;
	}

	DEV_INFO(CH34X_USBDEV,
		 "USB to SPI/I2C/GPIO adapter ch34x now attached.");

	return 0;

error5:
	WRITE_ONCE(ch34x_dev->disconnecting, true);
	ch34x_spi_remove(ch34x_dev);
error4:
	ch34x_mphsi_gpio_remove(ch34x_dev);
error3:
	if (use_irq)
		ch34x_irq_remove(ch34x_dev);
error2:
	ch34x_cfg_remove(ch34x_dev);
error1:
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 19, 0)
	ida_free(&ch34x_devid_ida, ch34x_dev->id);
#else
	ida_simple_remove(&ch34x_devid_ida, ch34x_dev->id);
#endif
error:
	ch34x_draw_down(ch34x_dev);
	ch34x_usb_free_device(ch34x_dev);

	return ret;

bad_endpoints:
	ret = -ENODEV;
	goto error;
}

static void ch34x_draw_down(struct ch34x_device *ch34x_dev)
{
	int i;

	for (i = 0; i < CH34X_NW; i++)
		if (ch34x_dev->wb[i].urb)
			usb_kill_urb(ch34x_dev->wb[i].urb);

	if (ch34x_dev->intr_urb)
		usb_kill_urb(ch34x_dev->intr_urb);
}

#ifdef CONFIG_PM
static int ch34x_usb_suspend(struct usb_interface *intf,
			     pm_message_t message)
{
	struct ch34x_device *ch34x_dev = usb_get_intfdata(intf);
	int cnt;

	spin_lock_irq(&ch34x_dev->write_lock);
	if (PMSG_IS_AUTO(message)) {
		if (ch34x_dev->transmitting) {
			spin_unlock_irq(&ch34x_dev->write_lock);
			return -EBUSY;
		}
	}
	cnt = ch34x_dev->susp_count++;
	spin_unlock_irq(&ch34x_dev->write_lock);
	if (cnt)
		return 0;
	ch34x_draw_down(ch34x_dev);

	return 0;
}

static int ch34x_usb_resume(struct usb_interface *intf)
{
	struct ch34x_device *ch34x_dev = usb_get_intfdata(intf);
	int rv = 0;

	spin_lock_irq(&ch34x_dev->write_lock);
	if (--ch34x_dev->susp_count)
		goto out;

	if (ch34x_dev->intr_urb)
		rv = usb_submit_urb(ch34x_dev->intr_urb, GFP_ATOMIC);

out:
	spin_unlock_irq(&ch34x_dev->write_lock);

	return rv;
}
#endif

static int ch34x_pre_reset(struct usb_interface *intf)
{
	struct ch34x_device *ch34x_dev = usb_get_intfdata(intf);

	mutex_lock(&ch34x_dev->io_mutex);
	ch34x_draw_down(ch34x_dev);

	return 0;
}

static int ch34x_post_reset(struct usb_interface *intf)
{
	struct ch34x_device *ch34x_dev = usb_get_intfdata(intf);

	ch34x_dev->errors = -EPIPE;
	mutex_unlock(&ch34x_dev->io_mutex);

	return 0;
}

static void ch34x_usb_disconnect(struct usb_interface *intf)
{
	struct ch34x_device *ch34x_dev = usb_get_intfdata(intf);

	DEV_INFO(CH34X_USBDEV, "CH34X adapter now disconnected");

	/* Stop the interrupt URB self-resubmit loop before killing URBs */
	WRITE_ONCE(ch34x_dev->disconnecting, true);
	ch34x_draw_down(ch34x_dev);

	ch34x_spi_remove(ch34x_dev);
	ch34x_mphsi_gpio_remove(ch34x_dev);
	if (ch34x_dev->irq_num)
		ch34x_irq_remove(ch34x_dev);
	ch34x_cfg_remove(ch34x_dev);
#if LINUX_VERSION_CODE >= KERNEL_VERSION(4, 19, 0)
	ida_free(&ch34x_devid_ida, ch34x_dev->id);
#else
	ida_simple_remove(&ch34x_devid_ida, ch34x_dev->id);
#endif
	ch34x_usb_free_device(ch34x_dev);
}

static struct usb_driver ch34x_usb_driver = {
	.name = "mphsi-ch34x",
	.id_table = ch34x_usb_ids,
	.probe = ch34x_usb_probe,
	.disconnect = ch34x_usb_disconnect,
	.suspend = ch34x_usb_suspend,
	.resume = ch34x_usb_resume,
	.pre_reset = ch34x_pre_reset,
	.post_reset = ch34x_post_reset,
};

module_usb_driver(ch34x_usb_driver);

MODULE_ALIAS(DRIVER_ALIAS);
MODULE_AUTHOR(DRIVER_AUTHOR);
MODULE_DESCRIPTION(DRIVER_DESC);
MODULE_VERSION(VERSION_DESC);
MODULE_LICENSE("GPL");

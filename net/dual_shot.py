# -*- coding:utf-8 _*-
"""
@author: danna.li
@date: 2019/4/24 
@file: dual_shot.py
@description:
"""
import keras.layers as KL
from keras import Model
from dual_conf import current_config as conf
import keras
from loss_func import progressive_anchor_loss
from net.vgg import extend_vgg
from net.resnet import extend_resnet

base_net = conf.base_net
print('using:', base_net, 'as the base model')


def classifier(x, name):
    cls = KL.Conv2D(conf.num_class, (1, 1), padding='same', name='cls_' + name)(x)
    regr = KL.Conv2D(4, (1, 1), activation='linear', padding='same', name='regr_' + name)(x)
    cls = KL.Reshape((-1, conf.num_class), name='reshape_cls_' + name)(cls)
    regr = KL.Reshape((-1, 4), name='reshape_regr_' + name)(regr)
    return cls, regr


def detector(conv3_3, conv4_3, conv5_3, conv_fc7, conv6_2, conv7_2, name):
    cls1, regr1 = classifier(conv3_3, 'conv3_3' + name)
    cls2, regr2 = classifier(conv4_3, 'conv4_3' + name)
    cls3, regr3 = classifier(conv5_3, 'conv5_3' + name)
    cls4, regr4 = classifier(conv_fc7, 'fc_7' + name)
    cls5, regr5 = classifier(conv6_2, 'conv6_2' + name)
    cls6, regr6 = classifier(conv7_2, 'conv7_2' + name)
    cls = KL.Concatenate(axis=1, name='cls_concat_' + name)([cls1, cls2, cls3, cls4, cls5, cls6])
    regr = KL.Concatenate(axis=1, name='regr_concat_' + name)([regr1, regr2, regr3, regr4, regr5, regr6])
    return cls, regr


def group_channel_conv(x_in, name):
    x1_1 = KL.Conv2D(256, (3, 3), dilation_rate=(1, 1), activation='relu', padding='same', name='dilated_1_1' + name)(
        x_in)
    x2_1 = KL.Conv2D(256, (3, 3), dilation_rate=(2, 2), activation='relu', padding='same', name='dilated_2_1' + name)(
        x_in)
    x2_2 = KL.Conv2D(128, (3, 3), dilation_rate=(1, 1), activation='relu', padding='same', name='dilated_2_2' + name)(
        x2_1)
    x3_1 = KL.Conv2D(128, (3, 3), dilation_rate=(2, 2), activation='relu', padding='same', name='dilated_3_1' + name)(
        x2_1)
    x3_2 = KL.Conv2D(128, (3, 3), dilation_rate=(1, 1), activation='relu', padding='same', name='dilated_3_2' + name)(
        x3_1)
    return KL.Concatenate()([x1_1, x2_2, x3_2])


def feature_enhance(x_current, x_deeper, channel, name):
    x_current = KL.Conv2D(channel, (1, 1), activation='relu', padding='same', name='current_norm_' + name)(x_current)
    x_deeper = KL.Conv2D(channel, (1, 1), activation='relu', padding='same', name='deeper_norm_' + name)(x_deeper)
    x_deeper = KL.UpSampling2D(size=(2, 2))(x_deeper)
    x_combine = KL.Multiply(name='element_dot_' + name)([x_current, x_deeper])
    x = group_channel_conv(x_combine, name)
    return x


def feature_enhance_module(conv3_3, conv4_3, conv5_3, conv_fc7, conv6_2, conv7_2):
    conv3_3_ef = feature_enhance(conv3_3, conv4_3, 256, 'conv3_3')
    conv4_3_ef = feature_enhance(conv4_3, conv5_3, 256, 'conv4_3')
    conv5_3_ef = feature_enhance(conv5_3, conv_fc7, 256, 'conv5_3')
    conv_fc7_ef = feature_enhance(conv_fc7, conv6_2, 256, 'conv_fc7')
    conv6_2_ef = feature_enhance(conv6_2, conv7_2, 256, 'conv6_2')
    conv7_2_ef = conv7_2
    return conv3_3_ef, conv4_3_ef, conv5_3_ef, conv_fc7_ef, conv6_2_ef, conv7_2_ef


def train_net(x_in, y_e_reg, y_e_cls, y_o_reg, y_o_cls):
    conv3_3, conv4_3, conv5_3, conv_fc7, conv6_2, conv7_2 = extend_resnet(x_in, base_net)
    # first shot
    fs_cls, fs_regr = detector(conv3_3, conv4_3, conv5_3, conv_fc7, conv6_2, conv7_2, 'fs')
    # second shot
    conv3_3_ef, conv4_3_ef, conv5_3_ef, conv_fc7_ef, conv6_2_ef, conv7_2_ef \
        = feature_enhance_module(conv3_3, conv4_3, conv5_3, conv_fc7, conv6_2, conv7_2)
    ss_cls, ss_regr = detector(conv3_3_ef, conv4_3_ef, conv5_3_ef, conv_fc7_ef, conv6_2_ef, conv7_2_ef, 'ss')
    pal = keras.layers.Lambda(lambda x: progressive_anchor_loss(*x), name='PAL')([y_e_reg, y_e_cls, y_o_reg, y_o_cls,
                                                                                  fs_cls, fs_regr, ss_cls, ss_regr])
    return fs_cls, fs_regr, ss_cls, ss_regr, pal


def test_net(x_in):
    conv3_3, conv4_3, conv5_3, conv_fc7, conv6_2, conv7_2 = extend_resnet(x_in, base_net)
    # second shot
    conv3_3_ef, conv4_3_ef, conv5_3_ef, conv_fc7_ef, conv6_2_ef, conv7_2_ef \
        = feature_enhance_module(conv3_3, conv4_3, conv5_3, conv_fc7, conv6_2, conv7_2)
    ss_cls, ss_regr = detector(conv3_3_ef, conv4_3_ef, conv5_3_ef, conv_fc7_ef, conv6_2_ef, conv7_2_ef, 'ss')
    return ss_cls, ss_regr


def net_test():
    net_in = KL.Input([640, 640, 3], name='image_array')
    y_e_reg = KL.Input((34125, 4), name='e_reg')
    y_e_cls = KL.Input((34125,), name='e_train_cls')
    y_o_reg = KL.Input((34125, 4), name='o_reg')
    y_o_cls = KL.Input((34125,), name='o_train_cls')
    fs_cls, fs_regr, ss_cls, ss_regr, pal = train_net(net_in, y_e_reg, y_e_cls, y_o_reg, y_o_cls)
    model = Model(inputs=[net_in, y_e_reg, y_e_cls, y_o_reg, y_o_cls], outputs=[fs_cls, fs_regr, ss_cls, ss_regr, pal])
    model.summary()
    # from keras.utils import plot_model
    # plot_model(model, to_file='model.png', show_shapes=True, show_layer_names=False)


if __name__ == '__main__':
    net_test()

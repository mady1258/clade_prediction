import time
import sys
import os

import random
import pandas as pd
import numpy as np
import logging
import glob
import tensorflow as tf
import matplotlib.pyplot as plt


import utils


RESULT_PATH = "test_results/20A_20C_14Sept_CPU/"
min_diff = 0
max_diff = 61
enc_units = 128
LEN_AA = 1273
seq_len = LEN_AA

clade_source = "20A"
clade_start = "20C"
generating_factor = 100


def load_model_generated_sequences():
    # load test data
    #te_clade_files = glob.glob('data/test/*.csv')
    te_clade_files = glob.glob(RESULT_PATH + 'test/*.csv')
    r_dict = utils.read_json(RESULT_PATH + "r_word_dictionaries.json")
    vocab_size = len(r_dict) + 1
    total_te_loss = list()
    #print("Loading trained model from {}...".format(RESULT_PATH))
    #loaded_encoder = tf.keras.models.load_model(RESULT_PATH + "enc_model")
    #loaded_generator = tf.keras.models.load_model(RESULT_PATH + "gen_model")
    #print(loaded_encoder)
    #print(loaded_generator)
    print("Generating sequences for {}...".format(clade_start))
    for te_name in te_clade_files:
        te_clade_df = pd.read_csv(te_name, sep="\t")
        te_X = te_clade_df["X"]
        te_y = te_clade_df["Y"]
        print(te_clade_df.shape)
        batch_size = te_clade_df.shape[0]
        with tf.device('/device:cpu:0'):
            #te_loss = predict_sequence(te_X, te_y, LEN_AA, vocab_size, batch_size, loaded_encoder, loaded_generator, generating_factor)
            predict_multiple(te_X, te_y, LEN_AA, vocab_size, batch_size)


def predict_multiple(test_x, test_y, seq_len, vocab_size, batch_size):
    batch_size = test_x.shape[0]

    test_dataset_in = tf.data.Dataset.from_tensor_slices((test_x)).batch(batch_size)
    test_dataset_out = tf.data.Dataset.from_tensor_slices((test_y)).batch(batch_size)

    true_x = list()
    true_y = list()
    predicted_y = list()

    num_te_batches = int(len(test_x) / float(batch_size))

    print("Num test batches: {}".format(str(num_te_batches)))

    for step, (x, y) in enumerate(zip(test_dataset_in, test_dataset_out)):
        batch_x_test = utils.pred_convert_to_array(x)
        batch_y_test = utils.pred_convert_to_array(y)
        print(batch_x_test.shape, batch_y_test.shape)
        print("Generating multiple sequences for each test sequence...")
        for i in range(generating_factor):

            print("Generating for iter {}/{}".format(str(i+1), str(generating_factor)))
            print("Loading trained model from {}...".format(RESULT_PATH))
            loaded_encoder = tf.keras.models.load_model(RESULT_PATH + "enc_model")
            loaded_generator = tf.keras.models.load_model(RESULT_PATH + "gen_model")
            
            noise = tf.random.normal((batch_size, enc_units))

            enc_output, enc_state = loaded_encoder(batch_x_test, training=False)
            enc_state = tf.math.add(enc_state, noise)

            print(batch_x_test.shape, noise.shape, enc_state.shape)

            generated_logits = gen_step_predict(seq_len, batch_size, vocab_size, loaded_generator, enc_state)
            p_y = tf.math.argmax(generated_logits, axis=-1)

            one_x = utils.convert_to_string_list(batch_x_test)
            one_y = utils.convert_to_string_list(batch_y_test)
            pred_y = utils.convert_to_string_list(p_y)
 
            l_x_gen = list()
            for k in range(0, len(one_x)):
               l_dist_x_pred = utils.compute_Levenshtein_dist(one_x[k], pred_y[k])
               if l_dist_x_pred > min_diff and l_dist_x_pred < max_diff:
                   l_x_gen.append(l_dist_x_pred)
                   true_x.append(one_x[k])
                   true_y.append(one_y[k])
                   predicted_y.append(pred_y[k])
            print(len(l_x_gen), l_x_gen)

            print("Step:{}, mean levenshtein distance (x and pred): {}".format(str(i+1), str(np.mean(l_x_gen))))
            print("Step:{}, median levenshtein distance (x and pred): {}".format(str(i+1), str(np.median(l_x_gen))))
            print("Step:{}, standard deviation levenshtein distance (x and pred): {}".format(str(i+1), str(np.std(l_x_gen))))
            print("Step:{}, variance levenshtein distance (x and pred): {}".format(str(i+1), str(np.var(l_x_gen))))
            #true_x.extend(one_x)
            #true_y.extend(one_y)
            #predicted_y.extend(pred_y)

            print("Generation iter {} done".format(str(i+1)))
            print("----------")
        print("Batch {} finished".format(str(step)))
        print()
    print(len(true_x), len(true_y), len(predicted_y))
    true_predicted_multiple = pd.DataFrame(list(zip(true_x, true_y, predicted_y)), columns=[clade_source, clade_start, "Generated"])
    df_path = "{}true_predicted_multiple_te_x_{}times.csv".format(RESULT_PATH, str(generating_factor))
    true_predicted_multiple.to_csv(df_path, index=None)
    

def gen_step_predict(seq_len, batch_size, vocab_size, gen_decoder, dec_state):
    step_loss = tf.constant(0.0)
    pred_logits = np.zeros((batch_size, seq_len, vocab_size))
    i_token = tf.fill([batch_size, 1], 0)
    for t in tf.range(seq_len):
        dec_result, dec_state = gen_decoder([i_token, dec_state], training=False)
        dec_numpy = dec_result.numpy()
        pred_logits[:, t, :] = np.reshape(dec_numpy, (dec_numpy.shape[0], dec_numpy.shape[2]))
        dec_tokens = tf.math.argmax(dec_result, axis=-1)
        i_token = dec_tokens
    pred_logits = tf.convert_to_tensor(pred_logits)
    return pred_logits


def predict_sequence(test_x, test_y, seq_len, vocab_size, batch_size, loaded_encoder, loaded_generator, generating_factor):
    test_dataset_in = tf.data.Dataset.from_tensor_slices((test_x)).batch(batch_size)
    test_dataset_out = tf.data.Dataset.from_tensor_slices((test_y)).batch(batch_size)
    true_x = list()
    true_y = list()
    predicted_y = list()
    num_te_batches = int(len(test_x) / float(batch_size))
    print("Num test batches: {}".format(str(num_te_batches)))
    for step, (x, y) in enumerate(zip(test_dataset_in, test_dataset_out)):
        batch_x_test = utils.pred_convert_to_array(x)
        batch_y_test = utils.pred_convert_to_array(y)
        new_tokens = tf.fill([batch_size, 1], 0)
        noise = tf.random.normal((batch_size, enc_units))
        enc_output, enc_state = loaded_encoder(batch_y_test, training=False)
        enc_state = tf.math.add(enc_state, noise)
        dec_state = enc_state
        generated_logits = gen_step_predict(seq_len, batch_size, vocab_size, loaded_generator, dec_state, batch_y_test)
        p_y = tf.math.argmax(generated_logits, axis=-1)
        one_x = utils.convert_to_string_list(batch_x_test)
        one_y = utils.convert_to_string_list(batch_y_test)
        pred_y = utils.convert_to_string_list(p_y)
        true_x.extend(one_x)
        true_y.extend(one_y)
        predicted_y.extend(pred_y)
        print("Batch {} finished".format(str(step)))
    print(len(true_x), len(true_y), len(predicted_y))
    true_predicted_df = pd.DataFrame(list(zip(true_x, true_y, predicted_y)), columns=[clade_source, clade_start, "Generated"])
    df_path = "{}true_predicted_df.csv".format(RESULT_PATH)
    true_predicted_df.to_csv(df_path, index=None)

if __name__ == "__main__":
    start_time = time.time()
    load_model_generated_sequences()
    end_time = time.time()
    print("Program finished in {} seconds".format(str(np.round(end_time - start_time, 2))))
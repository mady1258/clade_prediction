import time
import sys
import os

import random
import pandas as pd
import numpy as np
import logging
import tensorflow as tf

import matplotlib.pyplot as plt

import preprocess_sequences
import utils
import neural_network
import sequence_to_sequence
import container_classes
import train_model
import masked_loss


PATH_PRE = "data/ncov_global/"
PATH_SEQ = PATH_PRE + "spike_protein.fasta" #"ncov_global.fasta"
PATH_SEQ_CLADE = PATH_PRE + "ncov_global.tsv"
PATH_CLADES = "data/clade_in_clade_out.json"
KMER_SIZE = 3
EMBED_DIM = 4
BATCH_SIZE = 16

# https://www.tensorflow.org/text/tutorials/nmt_with_attention


def read_files():
    '''samples_clades = preprocess_sequences.get_samples_clades(PATH_SEQ_CLADE)
    
    clades_in_clades_out = utils.read_json(PATH_CLADES)

    print("Preprocessing sequences...")
    encoded_sequence_df, forward_dict, _ = preprocess_sequences.preprocess_seq(PATH_SEQ, samples_clades, KMER_SIZE)
    
    print("Generating cross product...")
    preprocess_sequences.make_cross_product(clades_in_clades_out, encoded_sequence_df)
    
    print("Transforming generated samples...")
    preprocess_sequences.transform_encoded_samples()
    
    print("Reading in/out sequences...")
    train_samples = preprocess_sequences.read_in_out_sequences()
    
    vocab_size, seq_len = utils.embedding_info(forward_dict, train_samples)
    
    train_x = train_samples["Sequence_x"].to_numpy()
    train_y = train_samples["Sequence_y"].to_numpy()

    train_x = [list(map(int, lst)) for lst in train_x]
    train_y = [list(map(int, lst)) for lst in train_y]
    '''
    print("Creating neural network...")
    
    embedding_dim = 4
    units = 16
    batch_size = 8
    seq_len = 50
    vocab_size = 250
    
    sample_input = [np.random.randint(vocab_size, size=seq_len) for i in range(3 * batch_size)]
    sample_input = np.array(sample_input)
    print(sample_input.shape)
    
    sample_output = [np.random.randint(vocab_size, size=seq_len) for i in range(3 * batch_size)]
    sample_output = np.array(sample_output)
    print(sample_output.shape)
    
    dataset_in = tf.data.Dataset.from_tensor_slices((sample_input)).batch(batch_size)
    dataset_out = tf.data.Dataset.from_tensor_slices((sample_output)).batch(batch_size)
    #dataset = dataset.batch(batch_size)

    '''print(dataset.take(1))
    
    for input_batch, output_batch in dataset.take(1):
        #print(input_batch[:5])
        print()
        #print(output_batch[:5])
        break'''
    #print(dataset_in.shape, dataset_out.shape)
    start_training(dataset_in, dataset_out, embedding_dim, units, batch_size, seq_len, vocab_size)

def start_training(input_batch, output_batch, embedding_dim, units, batch_size, seq_len, vocab_size):

    '''encoder = sequence_to_sequence.Encoder(vocab_size, embedding_dim, units)
    enc_output, enc_state = encoder(sample_input)
    print("Encoder output:")
    print(enc_output.shape, enc_state.shape)
    print()

    decoder = sequence_to_sequence.Decoder(vocab_size, embedding_dim, units)

    dec_output, dec_state = decoder(
        inputs = container_classes.DecoderInput(new_tokens=input_batch, enc_output=enc_output, mask=(input_batch != 0)), state = enc_state
    )
    print("Decoder output:")
    print(dec_output.logits.shape, dec_state.shape)
    print()'''
    
    model = train_model.TrainModel(
        embedding_dim, units,
        vocab_size,
        input_tokens=input_batch,
        output_tokens=output_batch,
        use_tf_function=False
    )

    # Configure the loss and optimizer
    model.compile(
        optimizer=tf.optimizers.Adam(),
        loss=masked_loss.MaskedLoss(),
    )
    
    print("Start training ...")
    
    epochs = 20
    
    for n in range(epochs):
        print("Loss after training step: {}".format(str(n+1)))
        batch_learning = model.train_step([input_batch, output_batch])
        print(batch_learning["batch_loss"].numpy())
        print()

if __name__ == "__main__":
    start_time = time.time()
    read_files()
    end_time = time.time()
    print("Program finished in {} seconds".format(str(np.round(end_time - start_time, 2))))

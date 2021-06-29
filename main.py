import time
import sys
import os

import random
import pandas as pd
import numpy as np
import logging
import tensorflow as tf

import preprocess_sequences
import utils
import neural_network


PATH_PRE = "data/ncov_global/"
PATH_SEQ = PATH_PRE + "spike_protein.fasta" #"ncov_global.fasta"
PATH_SEQ_CLADE = PATH_PRE + "ncov_global.tsv"
PATH_CLADES = "data/clade_in_clade_out.json"
KMER_SIZE = 3
EMBED_DIM = 4


def read_files():
    samples_clades = preprocess_sequences.get_samples_clades(PATH_SEQ_CLADE)
    
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
    
    print("Creating neural network...")
    generator = neural_network.make_generator_model(train_samples, vocab_size, EMBED_DIM, seq_len)
    
    print(generator.summary())

    #noise = tf.random.normal([1, 100])
    noise = tf.random.uniform(
        [seq_len], minval=1, maxval=vocab_size, dtype=tf.dtypes.int32, seed=None, name=None
    )
    print(noise)
    noise = np.random.randint(vocab_size, size=(1, seq_len))
    print(noise)
    generated_sequence = generator(noise, training=False)
    
    print(generated_sequence)

    '''discriminator = neural_network.make_discriminator_model()
    decision = discriminator(generated_image)
    print (decision)

    cross_entropy = tf.keras.losses.BinaryCrossentropy(from_logits=True)
    
    generator_optimizer = tf.keras.optimizers.Adam(1e-4)
    discriminator_optimizer = tf.keras.optimizers.Adam(1e-4)

    checkpoint = tf.train.Checkpoint(generator_optimizer=generator_optimizer,
                                 discriminator_optimizer=discriminator_optimizer,
                                 generator=generator,
                                 discriminator=discriminator)

    EPOCHS = 50
    noise_dim = 100
    num_examples_to_generate = 16
    
    print("Training neural network...")
    neural_network.train(train_samples, EPOCHS)
    
    # Generate after the final epoch
    display.clear_output(wait=True)
    generate_and_save_images(generator,
                           epochs,
                           seed)'''
    
    
    
    #print("Creating train data...")
    #preprocess_sequences.generate_batches()

if __name__ == "__main__":
    start_time = time.time()
    read_files()
    end_time = time.time()
    print("Program finished in {} seconds".format(str(np.round(end_time - start_time, 2))))

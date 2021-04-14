import sys
import os
import pandas as pd
import numpy as np
import json
import glob
from Bio import SeqIO

import utils

LEN_AA = 1275


def get_samples_clades(path_seq_clades):
    ncov_global_df = pd.read_csv(path_seq_clades, sep="\t")
    samples_clades = dict()
    for idx in range(len(ncov_global_df)):
        sample_row = ncov_global_df.take([idx])
        s_name = sample_row["strain"].values[0]
        clade_name = sample_row["Nextstrain_clade"].values[0]
        clade_name = utils.format_clade_name(clade_name)
        samples_clades[s_name] = clade_name
    utils.save_as_json("data/generated_files/samples_clades.json", samples_clades)
    return samples_clades


def preprocess_seq(fasta_file, samples_clades, kmer_size):
    encoded_samples = list()
    amino_acid_codes = "ARNDCQEGHILKMFPOSUTWYVBZXJ"
    max_seq_size = LEN_AA #LEN_AA - kmer_size + 1
    possible_words = utils.get_all_possible_words(kmer_size, amino_acid_codes)
    f_word_dictionaries, r_word_dictionaries = utils.get_words_indices(possible_words)
    for sequence in SeqIO.parse(fasta_file, "fasta"):
        row = list()
        seq_id = sequence.id.split("|")[1]
        sequence = str(sequence.seq)
        sequence = sequence.replace("*", '')
        if seq_id in samples_clades:
            row.append(seq_id)
            clade_name = samples_clades[seq_id]
            clade_name = utils.format_clade_name(clade_name)
            #print(clade_name)
            row.append(clade_name)
            kmers = utils.make_kmers(sequence, size=kmer_size)
            #print(len(kmers))
            indices_kmers = [str(r_word_dictionaries[i]) for i in kmers]
            #print(len(indices_kmers))
            #print(sequence)
            zeros = np.repeat('0', max_seq_size - len(indices_kmers))
            
            indices_kmers = np.hstack([indices_kmers, zeros])
            #print(len(indices_kmers), len(zeros))
            #print(indices_kmers)
            joined_indices_kmers = ','.join(indices_kmers)
            row.append(joined_indices_kmers)
            encoded_samples.append(row)
            #print()
    sample_clade_sequence_df = pd.DataFrame(encoded_samples, columns=["SampleName", "Clade", "Sequence"])
    sample_clade_sequence_df.to_csv("data/generated_files/sample_clade_sequence_df.csv", index=None)
    utils.save_as_json("data/generated_files/f_word_dictionaries.json", f_word_dictionaries)
    utils.save_as_json("data/generated_files/r_word_dictionaries.json", r_word_dictionaries)
    return sample_clade_sequence_df


def make_cross_product(clade_in_clade_out, dataframe):
    total_samples = 0
    for in_clade in clade_in_clade_out:
        # get df for parent clade
        in_clade_df = dataframe[dataframe["Clade"].replace("/", "_") == in_clade]
        in_len = len(in_clade_df.index)
        print("Size of clade {}: {}".format(in_clade, str(in_len)))
        # get df for child clades
        for out_clade in clade_in_clade_out[in_clade]:
            out_clade_df = dataframe[dataframe["Clade"].replace("/", "_") == out_clade]
            out_len = len(out_clade_df.index)
            # add tmp key to obtain cross join and then drop it
            in_clade_df["_tmpkey"] = np.ones(in_len)
            out_clade_df["_tmpkey"] = np.ones(out_len)
            cross_joined_df = pd.merge(in_clade_df, out_clade_df, on="_tmpkey").drop("_tmpkey", 1)
            print("Size of clade {}: {}".format(out_clade, str(out_len)))
            merged_size = in_len * out_len
            print("Merged size ({} * {}) : {}".format(str(in_len), str(out_len), merged_size))
            print()
            total_samples += merged_size
            file_name = "data/merged_clades/{}_{}.csv".format(in_clade, out_clade)
            cross_joined_df.to_csv(file_name, sep="\t", index=None)
            break
        break
    print()
    print("Total number of samples: {}".format(str(total_samples)))
    
    
def transform_encoded_samples(train_size=0.8):
    clade_files = glob.glob('data/merged_clades/*.csv')
    for name in clade_files:
        file_path_w_ext = os.path.splitext(name)[0]
        file_name_w_ext = os.path.basename(file_path_w_ext)
        clade_df = pd.read_csv(name, sep="\t")
        # randomize rows
        clade_df = clade_df.sample(frac=1)
        train_df = clade_df.sample(frac=train_size, random_state=200)
        test_df = clade_df.drop(train_df.index)
        train_file_path = "data/train/{}.csv".format(file_name_w_ext)
        test_file_path = "data/test/{}.csv".format(file_name_w_ext)
        #train_df = train_df.drop(["SampleName_x", "Clade_x", "SampleName_y", "Clade_y"], axis=1)
        #test_df = test_df.drop(["SampleName_x", "Clade_x", "SampleName_y", "Clade_y"], axis=1)
        train_df.to_csv(train_file_path, sep="\t", index=None)
        test_df.to_csv(test_file_path, sep="\t", index=None)


def read_in_out_sequences():
    train_file_path = "data/train/19A_19B.csv"
    data_df = pd.read_csv(train_file_path, sep="\t")
    train_samples = data_df[['Sequence_x', 'Sequence_y']]
    train_samples["Sequence_x"] = train_samples["Sequence_x"].str.split(",")
    train_samples["Sequence_y"] = train_samples["Sequence_y"].str.split(",")
    return train_samples

#def generate_uniform_batch(file_dir, batch_size=100):
    


#def normalize_sequences():
    
    
    

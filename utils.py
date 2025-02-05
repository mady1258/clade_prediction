import os
import sys
import shutil
import itertools
from itertools import product
import json
import pandas as pd
import numpy as np
import random
from random import choices
from scipy.spatial import distance
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'
import tensorflow as tf
#import tensorflow_probability as tfp
from scipy.stats.stats import pearsonr
from tensorflow.keras import backend as K
from sklearn.utils import class_weight
from sklearn.preprocessing import LabelEncoder
from sklearn.preprocessing import RobustScaler
from sklearn.cluster import OPTICS
from sklearn.cluster import KMeans
from sklearn import metrics
from Levenshtein import distance as lev_dist
from focal_loss import sparse_categorical_focal_loss

from focal_loss import SparseCategoricalFocalLoss
tf.keras.metrics.SparseTopKCategoricalAccuracy(k=1)

import neural_network

PATH_KMER_F_DICT = "data/ncov_global/kmer_f_word_dictionaries.json"
PATH_KMER_R_DICT = "data/ncov_global/kmer_r_word_dictionaries.json"

m_loss = neural_network.MaskedLoss()
bce = tf.keras.losses.BinaryCrossentropy(from_logits=False)
#focal_loss_func = SparseCategoricalFocalLoss(gamma=2)

cross_entropy_loss = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True, reduction='none')

mae = tf.keras.losses.MeanAbsoluteError()
mse = tf.keras.losses.MeanSquaredError()
test_tf_ratio = 0.0
enc_stddev = 1.0 # 0.05 for pretraining
max_norm = 1.0
dec_stddev = 1.0 #0.0001
max_batch_turn = 50
#pos_variations = dict()
amino_acid_codes = "QNKWFPYLMTEIARGHSDVC"


def loss_function(real, pred):
  # real shape = (BATCH_SIZE, max_length_output)
  # pred shape = (BATCH_SIZE, max_length_output, tar_vocab_size )
  cross_entropy = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=False, reduction='none')
  loss = cross_entropy(y_true=real, y_pred=pred)
  #mask = tf.logical_not(tf.math.equal(real, 0))  #output 0 for y=0 else output 1
  #mask = tf.cast(mask, dtype=loss.dtype)  
  #loss = mask* loss
  loss = tf.reduce_mean(loss)
  return loss 


def make_kmers(seq, size):
    return ["".join(seq[x:x+size]) for x in range(len(seq) - size + 1)]


def compute_Levenshtein_dist(seq_in, seq_out):
    #return np.random.randint(1, 5)
    return lev_dist(seq_in, seq_out)


def clean_up(list_folders):
    for folder in list_folders:
        try:
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    shutil.rmtree(file_path)
        except Exception as e:
            print('Failed to delete %s. Reason: %s' % (folder, e))
            continue


def add_padding_to_seq(seq, s_token):
    return "{},{}".format(str(s_token), seq)


def get_u_kmers(x_seq, y_seq, max_l_dist, len_aa_subseq, forward_dict, start_token):
    x_list = list()
    y_list = list()
    s_kmer = 3
    for i, x_i in enumerate(x_seq):
        for j, y_j in enumerate(y_seq):
            # cut sequences of specific length
            sub_x_i = x_i.split(",")[:len_aa_subseq]
            sub_x_i = ",".join(sub_x_i)
            sub_y_j = y_j.split(",")[:len_aa_subseq]
            sub_y_j = ",".join(sub_y_j)
            x_list.append(sub_x_i)
            y_list.append(sub_y_j)

    kmer_f_dict, kmer_r_dict = get_all_possible_words(amino_acid_codes, s_kmer)
    #global_kmers = get_all_kmers(x_list, y_list, forward_dict, s_kmer)
    #global_kmers = list(set(global_kmers))
    #kmer_f_dict = {i + 1: global_kmers[i] for i in range(0, len(global_kmers))}
    #kmer_r_dict = {global_kmers[i]: i + 1  for i in range(0, len(global_kmers))}

    kmer_f_dict[start_token] = "<start>"
    kmer_r_dict["<start>"] = start_token

    #print(kmer_f_dict)

    save_as_json(PATH_KMER_F_DICT, kmer_f_dict)
    save_as_json(PATH_KMER_R_DICT, kmer_r_dict)

    enc_x, enc_y = encode_sequences_kmers(forward_dict, kmer_r_dict, x_list, y_list, s_kmer)
    fil_x = list()
    fil_y = list()
    l_distance = list()
    filtered_l_distance = list()
    for i, (enc_i, enc_j) in enumerate(zip(enc_x, enc_y)):
        re_x = reconstruct_seq([kmer_f_dict[int(pos)] for pos in enc_i.split(",")])
        re_y = reconstruct_seq([kmer_f_dict[int(pos)] for pos in enc_j.split(",")])
        l_dist = compute_Levenshtein_dist(re_x, re_y)
        l_distance.append(l_dist)
        if l_dist > 0 and l_dist < max_l_dist:
            filtered_l_distance.append(l_dist)
            fil_x.append(add_padding_to_seq(enc_i, start_token))
            fil_y.append(add_padding_to_seq(enc_j, start_token))
            #fil_x.append(enc_i)
            #fil_y.append(enc_j)
    return fil_x, fil_y, kmer_f_dict, kmer_r_dict


def split_test_train(x, y, split_size):
    size = int(len(x) * split_size)
    x_1, y_1 = x[0:size], y[0:size]
    x_2, y_2 = x[size:], y[size:]
    return x_1, x_2, y_1, y_2 


def generate_cross_product(x_seq, y_seq, max_l_dist, len_aa_subseq, forward_dict, rev_dict, start_token, cols=["X", "Y"], unrelated=False, unrelated_threshold=15):
    print(len(x_seq), len(y_seq))
    x_y = list(itertools.product(x_seq, y_seq))
    print(len(x_y))
    print("Filtering for range of levenshtein distance...")
    l_distance = list()
    filtered_l_distance = list()
    filtered_x = list()
    filtered_y = list()

    kmer_f_dict = dict()
    kmer_r_dict = dict()

    #print(forward_dict)
    filtered_x, filtered_y, kmer_f_dict, kmer_r_dict = get_u_kmers(x_seq, y_seq, max_l_dist, len_aa_subseq, forward_dict, start_token)
    
    '''for i, x_i in enumerate(x_seq):
        for j, y_j in enumerate(y_seq):
            # cut sequences of specific length
            
            sub_x_i = x_i.split(",")[:len_aa_subseq]
            sub_x_i = ",".join(sub_x_i)
            #print(len(x_i.split(",")), len(sub_x_i.split(",")))

            sub_y_j = y_j.split(",")[:len_aa_subseq]
            sub_y_j = ",".join(sub_y_j)
            #print(len(y_j.split(",")), len(sub_y_j.split(",")))

            re_x = reconstruct_seq([forward_dict[pos] for pos in sub_x_i.split(",")])
            re_y = reconstruct_seq([forward_dict[pos] for pos in sub_y_j.split(",")])

            #print(sub_x_i, re_x)
            #print(sub_y_j, re_y)
            l_dist = compute_Levenshtein_dist(sub_x_i, sub_y_j)
            #print(l_dist)
            #print("-----")
            
            l_distance.append(l_dist)
            if unrelated is False:
                if l_dist > 0 and l_dist < max_l_dist:
                    filtered_x.append(add_padding_to_seq(sub_x_i, start_token))
                    filtered_y.append(add_padding_to_seq(sub_y_j, start_token))
                    filtered_l_distance.append(l_dist)
            else:
                if l_dist > max_l_dist:
                    filtered_x.append(add_padding_to_seq(sub_x_i, start_token))
                    filtered_y.append(add_padding_to_seq(sub_y_j, start_token))
                    filtered_l_distance.append(l_dist)'''

    print(len(filtered_l_distance), np.mean(filtered_l_distance))
    filtered_dataframe = pd.DataFrame(list(zip(filtered_x, filtered_y)), columns=["X", "Y"])
    print("Combined dataframe size: {}".format(str(len(filtered_dataframe.index))))
    np.savetxt("data/generated_files/l_distance.txt", l_distance)
    np.savetxt("data/generated_files/filtered_l_distance.txt", filtered_l_distance)
    print("Mean levenshtein dist: {}".format(str(np.mean(l_distance))))
    print("Mean filtered levenshtein dist: {}".format(str(np.mean(filtered_l_distance))))
    print("Filtered dataframe size: {}".format(str(len(filtered_dataframe.index))))
    return filtered_dataframe, kmer_f_dict, kmer_r_dict


def transform_noise(noise):
    shp = noise.shape
    binary = np.random.choice([0, 1], shp[0] * shp[1])
    binary_reshape = np.reshape(binary, (shp[0], shp[1]))
    noise *= binary_reshape
    return tf.convert_to_tensor(noise, dtype=tf.float32)


def get_all_possible_words(vocab, kmer_size=3):
    all_com = [''.join(c) for c in product(vocab, repeat=kmer_size)]
    kmer_f_dict = {i + 1: all_com[i] for i in range(0, len(all_com))}
    kmer_r_dict = {all_com[i]: i + 1  for i in range(0, len(all_com))}
    #save_as_json(PATH_KMER_F_DICT, kmer_f_dict)
    #save_as_json(PATH_KMER_R_DICT, kmer_r_dict)
    return kmer_f_dict, kmer_r_dict


def convert_to_array(str_data):
    tolst = str_data.tolist()
    f_list = [item.split(",") for item in tolst]
    toarray = np.array([list(map(int, lst)) for lst in f_list])
    tensor = tf.convert_to_tensor(toarray, dtype=tf.int32)
    return toarray


def pred_convert_to_array(str_data):
    tolst = str_data.numpy()
    f_list = [item.decode("utf-8").split(",") for item in tolst]
    toarray = np.array([list(map(int, lst)) for lst in f_list])
    return tf.convert_to_tensor(toarray, dtype=tf.int32)


def format_POS_variations(var_pos):
    for key in var_pos:
       var_pos[key] = np.unique(var_pos[key].tolist())
    print(var_pos[key])

  
def one_hot_encoding():
    encoded_seq = list()
    for char in sequence:
        one_hot = np.zeros(len(aa_chars))
        one_hot[int(r_word_dictionaries[char]) - 1] = 1
        encoded_seq.append(one_hot)
        
    print(encoded_seq)
    #print(len(indices_kmers))
    #print(sequence)
    #print(np.zeros(len(aa_chars)))
    #zeros = np.repeat(np.zeros(len(aa_chars)), (LEN_AA - len(sequence) + 1))
    #print(zeros)
    print()
    trailing_zeros = list()
    for i in range(LEN_AA - len(sequence)):
        trailing_zeros.append(np.zeros(len(aa_chars)))
    print(trailing_zeros)
    
    encoded_seq.extend(trailing_zeros)
    print()
    print(encoded_seq)
    encoded_seq = np.array(encoded_seq)
    print(encoded_seq.shape)


def read_in_out(path):
    data_df = pd.read_csv(path, sep="\t")
    samples = data_df[['Sequence_x', 'Sequence_y']]
    samples["Sequence_x"] = samples["Sequence_x"].str.split(",")
    samples["Sequence_y"] = samples["Sequence_y"].str.split(",")
    return samples


def reconstruct_seq(kmers):
    reconstructed_seq = []
    for i, km in enumerate(kmers):
         if i < len(kmers) - 1:
             reconstructed_seq.append(km[0])
         else:
             reconstructed_seq.append(km)
    return "".join(reconstructed_seq)


def encode_sequences_kmers(f_dict, kmer_r_dict, x_seq, y_seq, s_kmer):
    in_seq = list()
    out_seq = list()
    for index, (x, y) in enumerate(zip(x_seq, y_seq)):
        x = x.split(",") #[1:]
        x_chars = [str(f_dict[i]) for i in x]
        x_seq = ",".join(x_chars)
        #print(x_seq)
        y = y.split(",") #[1:]
        y_chars = [str(f_dict[i]) for i in y]
        y_seq = ",".join(y_chars)

        x_kmers = make_kmers(x_chars, s_kmer)

        #print(x_kmers)
        encoded_x = [str(kmer_r_dict[str(i)]) for i in x_kmers]
        encoded_x = ",".join(encoded_x) #+ "," + str(len(kmer_r_dict) - 1)
        in_seq.append(encoded_x)

        y_kmers = make_kmers(y_chars, s_kmer)
        encoded_y = [str(kmer_r_dict[str(i)]) for i in y_kmers]
        encoded_y = ",".join(encoded_y) #+ "," + str(len(kmer_r_dict) - 1)
        out_seq.append(encoded_y)

    return in_seq, out_seq


def get_all_kmers(x_seq, y_seq, f_dict, s_kmer):
    all_kmers = list()
    for index, (x, y) in enumerate(zip(x_seq, y_seq)):
        x = x.split(",") #[1:]
        x_chars = [str(f_dict[i]) for i in x]
        x_seq = ",".join(x_chars)

        y = y.split(",") #[1:]
        y_chars = [str(f_dict[i]) for i in y]
        y_seq = ",".join(y_chars)

        x_kmers = make_kmers(x_chars, s_kmer)
        y_kmers = make_kmers(y_chars, s_kmer)

        u_x_mers = list(set(x_kmers))
        u_y_mers = list(set(y_kmers))

        all_kmers.extend(u_x_mers)
        all_kmers.extend(u_y_mers)

    return list(set(all_kmers))


'''def ordinal_to_kmer(seq_df, f_dict, r_dict, kmer_f_dict, kmer_r_dict, kmer_s=3):
    in_seq = list()
    out_seq = list()
    for index, (x, y) in seq_df.iterrows():
        x = x.split(",")[1:]
        x_chars = [str(f_dict[i]) for i in x]
        x_seq = ",".join(x_chars)

        y = y.split(",")[1:]
        y_chars = [str(f_dict[i]) for i in y]
        y_seq = ",".join(y_chars)

        x_kmers = make_kmers(x_chars, kmer_s)
        y_kmers = make_kmers(y_chars, kmer_s)

        encoded_x = [str(kmer_r_dict[str(i)]) for i in x_kmers]
        encoded_x = "0," + ",".join(encoded_x)
        in_seq.append(encoded_x)
        encoded_y = [str(kmer_r_dict[str(i)]) for i in y_kmers]
        encoded_y = "0," + ",".join(encoded_y)
        out_seq.append(encoded_y)

        # reconstruct seq from predicted kmers
        enc_x = encoded_x.split(",")[1:]
        print(enc_x)
        print()
        enc_x = [kmer_f_dict[int(i)] for i in enc_x]
        print(enc_x)
        orig_x = reconstruct_seq(enc_x)
        print()
        print(orig_x, len(orig_x))
        
    enc_df = pd.DataFrame(list(zip(in_seq, out_seq)), columns=seq_df.columns)
    return enc_df'''
        

def read_wuhan_seq(wu_path, rev_dict):
    with open(wu_path, "r") as wu_file:
        wuhan_seq = wu_file.read()
        wuhan_seq = wuhan_seq.split("\n")
        wuhan_seq = "".join(wuhan_seq)
        enc_wu_seq = [str(rev_dict[item]) for item in wuhan_seq]
        return ",".join(enc_wu_seq)


def get_words_indices(word_list):
    forward_dictionary = {i + 1: word_list[i] for i in range(0, len(word_list))}
    reverse_dictionary = {word_list[i]: i + 1  for i in range(0, len(word_list))}

    forward_dictionary["0"] = "<start>"
    reverse_dictionary["<start>"] = "0"

    return forward_dictionary, reverse_dictionary


def save_as_json(filepath, data):
    with open(filepath, 'w') as fp:
        json.dump(data, fp)


def read_json(path):
    with open(path, 'r') as fp:
        f_content = json.loads(fp.readline())
        return f_content
        

def format_clade_name(c_name):
    return c_name.replace("/", "_")
    
    
def embedding_info(dict_json):
    return len(dict_json)
    
def convert_to_string_list(l):
    try:
        l = l.numpy()
    except Exception:
        pass
    l = [",".join([str(i) for i in item]) for item in l]
    return l


def get_variation_loss(true_in, true_out, pred_logits):
    #print(true_in.shape, pred_logits.shape)
    one_hot_true_x = tf.one_hot(true_in[:, 1:], depth=pred_logits.shape[-1], axis=-1)
    one_hot_true_y = tf.one_hot(true_out[:, 1:], depth=pred_logits.shape[-1], axis=-1)

    mse_x = mse(one_hot_true_x, pred_logits)
    mse_y = mse(one_hot_true_y, pred_logits)
    return mse_y + (1.0 - mse_x)


def get_sequence_variation_percentage(true_in, pred_logits):
    seq_tokens = tf.math.argmax(pred_logits, axis=-1)
    i_tokens = convert_to_string_list(true_in)
    o_tokens = convert_to_string_list(seq_tokens)
    df_seqs = pd.DataFrame(list(zip(i_tokens, o_tokens)), columns=["X", "Pred"])
    u_df_seqs = df_seqs.drop_duplicates()
    pair_percent_variation = len(u_df_seqs.index) / float(len(df_seqs.index))
    df_x = df_seqs["X"].drop_duplicates()
    df_pred = df_seqs["Pred"].drop_duplicates()
    x_percent_variation = len(df_x.index) / float(len(df_seqs.index))
    pred_percent_variation = len(df_pred.index) / float(len(df_seqs.index))
    print("Variation scores, true x: {}, pred y: {}, x_pred pair: {}".format(str(x_percent_variation), str(pred_percent_variation), str(pair_percent_variation)))
    return x_percent_variation, pred_percent_variation, pair_percent_variation


def sample_unrelated_x_y(unrelated_X, unrelated_y, batch_size):
    un_rand_row_index = np.random.randint(0, unrelated_X.shape[0], batch_size)
    un_X = unrelated_X[un_rand_row_index]
    un_y = unrelated_y[un_rand_row_index]
    return convert_to_array(un_X), convert_to_array(un_y)


def scale_encodings(encoding):
    encoding = encoding.numpy()
    tf_enc = RobustScaler().fit_transform(encoding)
    return tf.convert_to_tensor(tf_enc, dtype=tf.float32)


def stateful_encoding(size_stateful, inputs, enc, training=False):
    stateful_batches = list()
    n_stateful_batches = int(inputs.shape[1]/float(size_stateful))
    for i in range(n_stateful_batches):
        s_batch = inputs[:, i*size_stateful: (i+1)*size_stateful]
        enc_out, enc_state_h, enc_state_c = enc(s_batch, training=training)
    return enc_out, enc_state_h, enc_state_c, enc


def clip_weights(tensor, clip_min=-1e-2, clip_max=1e-2):
    return tf.clip_by_value(tensor, clip_value_min=clip_min, clip_value_max=clip_max)
    #return tf.clip_by_norm(tensor, clip_norm=2.0)


def compute_enc_distance(enc_mat):
    dist = np.zeros((enc_mat.shape[0], enc_mat.shape[0])) #tf.fill([enc_mat.shape[0], enc_mat.shape[0]], 0) #
    ref_dist = np.zeros((enc_mat.shape[0], enc_mat.shape[0])) #tf.fill([enc_mat.shape[0], enc_mat.shape[0]], 0) #
    #dist = tf.Variable(dist)
    for i in range(enc_mat.shape[0]):
        for j in range(enc_mat.shape[0]):
            dist[i, j] = distance.euclidean(enc_mat[i], enc_mat[j])
            if i != j:
                ref_dist[i, j] = 1.0
    dist = tf.convert_to_tensor(dist, dtype=tf.float32)
    ref_dist = tf.convert_to_tensor(ref_dist, dtype=tf.float32)
    return dist #1 - tf.reduce_mean(dist) #tf.math.reduce_mean(ref_dist - dist)
    #print(tf.matmul(enc_mat, enc_mat, transpose_b=True))
    #prod = 1 - tf.matmul(enc_mat, enc_mat, transpose_b=True) # transpose second matrix)
    #prod = tf.matmul(enc_mat, enc_mat, transpose_b=True) # transpose second matrix)
    #dist = 1 - prod
    #print("Cosine dist:", dist)
    #return dist


def find_cluster_indices(output_seqs, batch_size):
    ## Cluster the output set of sequences and chooose sequences randomly from each cluster
    ### 
    '''fixed_seq_split = fixed_seq.split(",")
    diff_index = np.zeros(len(unrolled_x))
    #print(diff_index)
    print(fixed_seq_split)
    print()
    for index_x, x in enumerate(unrolled_x):
        x_sp = x.split(",")
        for i, aa in enumerate(fixed_seq_split):
            #print(aa, x_sp[i])
            if aa != x_sp[i]:
               diff_index[index_x] += 1
        #if index_x == 5:
        #    break
        print(x.split(","))
        print(diff_index[index_x])
        print("-------------")'''
 
    
    features = convert_to_array(output_seqs)

    #print(features, features.shape)

    clustering_type = OPTICS(min_samples=2, min_cluster_size=2)
    #clustering_type = KMeans(n_clusters=batch_size, random_state=0)
    cluster_labels = clustering_type.fit_predict(features)

    #print(cluster_labels, len(cluster_labels))

    x = list()
    y = list()
    cluster_indices_dict = dict()
    for i, l in enumerate(cluster_labels):
        x.append(output_seqs[i])
        y.append(l)
        if l not in cluster_indices_dict:
            cluster_indices_dict[l] = list()
        cluster_indices_dict[l].append(i)

    #print(cluster_indices_dict)

    scatter_df = pd.DataFrame(list(zip(x, y)), columns=["output_seqs", "clusters"])

    #print(scatter_df)

    scatter_df.to_csv("data/generated_files/clustered_output_seqs_data.csv")
    
    #import sys
    #sys.exit()

    return cluster_labels, cluster_indices_dict


def pairwise_dist(A, B):
    # https://gist.github.com/mbsariyildiz/34cdc26afb630e8cae079048eef91865
    # squared norms of each row in A and B
    na = tf.reduce_sum(tf.square(A), 1)
    nb = tf.reduce_sum(tf.square(B), 1)
    # na as a row and nb as a co"lumn vectors
    na = tf.reshape(na, [-1, 1])
    nb = tf.reshape(nb, [1, -1])
    # return pairwise euclidead difference matrix
    #D = na - (2 * tf.matmul(A, A, False, True)) + nb
    #D = D / tf.reduce_sum(D)
    #D = tf.square(D)
    #D = 1 - tf.reduce_mean(tf.sqrt(tf.maximum(na - 2*tf.matmul(A, A, False, True) + nb, 0.0)))
    #D = 1 - tf.reduce_mean(tf.maximum(na - 2*tf.matmul(A, A, False, True) + nb, 0.0))
    #D = 1 - tf.reduce_mean(1 - (1 - tf.reduce_sum((tf.expand_dims(A, 1) - tf.expand_dims(A, 0))**2, 2)))
    '''r = tf.reduce_sum(A*A, 1)
    r = tf.reshape(r, [-1, 1])
    D = tf.sqrt(r - 2 * tf.matmul(A, tf.transpose(A)) + tf.transpose(r))'''
    D = na - 2*tf.matmul(A, B, False, True) + nb
    #print(D)
    #D = D / tf.reduce_sum(D)
    #print(A)
    #print()
    #print(D)

    #D = tf.linalg.LinearOperatorLowerTriangular(D)

    #D = tf.math.abs(D)
    
    D_min = tf.math.reduce_min(D)
    D_max = tf.math.reduce_max(D)

    D = (D - D_min) / ((D_max - D_min) + 1e-10)

    #print(D)

    #print()
    #print(D_max)
    D = 1.0 - D
    zeros = tf.fill([A.shape[0]], 0.0)
    D = tf.linalg.set_diag(D, zeros)
    #print(D)
    D_mean = tf.math.abs(tf.reduce_mean(D))
    D_norm = tf.math.abs(1.0 - tf.norm(D))
    #D_mean = 1.0 - tf.reduce_mean(tf.math.abs(D))
    #print()
    #print("Mean Euclidean distance: ", D_mean)
    #D_norm = tf.math.abs(1.0 - tf.norm(D))
    #print(D_mean, tf.norm(D), D_norm)
    #print(D_mean, D_norm)
    return D_mean, D_norm, D


def get_pearson_coeff(enc_matr):
    pearson_coeff = list()
    for i, x in enumerate(enc_matr):
        for j, y in enumerate(enc_matr):
            pearson_coeff.append(pearsonr(x, y)[0])
    return np.mean(np.array(pearson_coeff))


def create_dirs(folder_path):
    if not os.path.isdir(folder_path):
        os.mkdir(folder_path)


def loop_encode_decode(seq_len, batch_size, vocab_size, input_tokens, output_tokens, gen_encoder, gen_decoder, enc_units, tf_ratio, train_test, s_stateful, mut_freq, pos_variations, pos_variations_count, batch_step):
    show = 2
    enc_output, enc_state = gen_encoder(input_tokens)
    #print(enc_state[:, :5])
    #print()
    #enc_corr = get_pearson_coeff(enc_state)
    #print(corr)
    #print()
    #print("---------")
    #print(tf.linalg.normalize(enc_state, ord=np.inf)[0])
    dec_state = enc_state
    #print(dec_state)
    #print()
    #enc_mean_dist, enc_pw_norm, eu_dist = pairwise_dist(dec_state, dec_state)
    #print(eu_dist)
    loss_enc_state_norm = tf.math.abs(max_norm - tf.norm(dec_state))
    dec_state = tf.math.add(dec_state, tf.random.normal((dec_state.shape[0], dec_state.shape[1]), stddev=enc_stddev))
    #print(tf.norm(enc_state).numpy(), tf.norm(dec_state).numpy())
    #(dec_state)
    #print("---------")
    #enc_state_norm_noise = tf.math.abs(max_norm - tf.norm(dec_state))
    #print()
    #print(dec_state[:show, :])
    loss = tf.constant(0.0)
    gen_logits = list()
    #o_state_norm = list()
    #dec_state_mean_dist = tf.constant(0.0)
    #dec_state_loop_pw_norm = tf.constant(0.0)
    #dec_step_norm = tf.constant(0.0)
    loss_dec_loop_norm = tf.constant(0.0)
    #dec_loop_pw_norm = tf.constant(0.0)
    #dec_loop_mean_dist = tf.constant(0.0)
    #dec_loop_corr = tf.constant(0.0)
    #mut_error_factor = tf.constant(1.0)
    free_run_loops = int(0.33 * seq_len)
    free_run_s_index = np.random.randint(0, seq_len - free_run_loops, 1)[0]
    i_tokens = tf.fill([batch_size, 1], 0)
    #print(pos_variations_count)
    #gamma_nos = np.random.gamma(1, size=seq_len)
    #rand_pos = random.sample(range(0, seq_len - 1), (seq_len - 1) // 2) #np.random.randint(0, seq_len - 1, (seq_len - 1) // 4)
    for t in range(seq_len - 1):
        dec_result, dec_state = gen_decoder([i_tokens, dec_state])
        dec_state = tf.math.add(dec_state, tf.random.normal((dec_state.shape[0], dec_state.shape[1]), stddev=dec_stddev))
        #dec_state_mean_dist, dec_state_loop_pw_norm, _ = pairwise_dist(dec_state, dec_state)
        #dec_loop_mean_dist += dec_state_mean_dist
        #loss_dec_state_norm = tf.math.abs(max_norm - tf.norm(dec_state))
        #loss_dec_loop_norm += loss_dec_state_norm
        #dec_loop_pw_norm += dec_state_loop_pw_norm
        gen_logits.append(dec_result)
        #dec_loop_corr += get_pearson_coeff(dec_state)
        if len(output_tokens) > 0:
            o_tokens = output_tokens[:, t+1:t+2]
            #step_loss = mut_error_factor * tf.reduce_mean(cross_entropy_loss(o_tokens, dec_result))
            #print(o_tokens)
            #print(tf.repeat(batch_size, repeats=tf.constant(batch_size)))
            #print(tf.repeat(o_tokens, repeats=tf.repeat(batch_size, repeats=tf.constant(batch_size))))
            #print(pos_variations[str(t)])

            # collect different variations at each POS
            u_var_distribution = np.array(list(pos_variations_count[str(t)].values()))
            unique_cls = np.array(list(pos_variations_count[str(t)].keys()))

            all_cls = tf.repeat(unique_cls, repeats=u_var_distribution).numpy()
            random.shuffle(all_cls)
            y = all_cls
            classes = unique_cls
            le = LabelEncoder()
            y_ind = le.fit_transform(y)
            recip_freq = len(y) / (len(le.classes_) * np.bincount(y_ind).astype(np.float64))
            class_wt = recip_freq[le.transform(classes)]
            beta = 0.999
            #print(pos_variations_count[str(t)])
            s_wts = np.sum(class_wt)

            class_var_pos = dict()
            norm_class_var_pos = dict()
            exp_class_var_pos = dict()
            real_class_wts = list()
            for k_i, key in enumerate(unique_cls):
            #    # loss input taken from paper: https://arxiv.org/pdf/1901.05555.pdf
                class_var_pos[key] = class_wt[k_i] #/ float(s_wts)
                norm_class_var_pos[key] = class_wt[k_i] / float(s_wts)
                exp_class_var_pos[key] = (1 - beta) / (1 - beta ** pos_variations_count[str(t)][key])
                real_class_wts.append(exp_class_var_pos[key])
            #print(class_var_pos)
            #print(norm_class_var_pos)
            #print(exp_class_var_pos)

            for key in exp_class_var_pos:
                exp_class_var_pos[key] = exp_class_var_pos[key] / np.sum(real_class_wts)

            #print(exp_class_var_pos)
            exp_norm_u_var_distribution = np.zeros((batch_size))
            uniform_wts = np.zeros((batch_size))
            for pos_idx, pos in enumerate(np.reshape(o_tokens, (batch_size,))):
                exp_norm_u_var_distribution[pos_idx] = exp_class_var_pos[pos] #/ float(np.sum(real_class_wts))
                #uniform_wts[pos_idx] = 1.0 #/ float(batch_size)
            #print(exp_norm_u_var_distribution)
            #exp_norm_u_var_distribution = exp_norm_u_var_distribution / np.sum(exp_norm_u_var_distribution)
            #print(o_tokens)
            #print(exp_norm_u_var_distribution)
            #print(uniform_wts)

            # introduce randomness
            #-------------------
            '''temp = 0.8
            dec_result = tf.math.log(dec_result / temp)
            dec_result = tf.math.exp(dec_result) / float(dec_result.shape[-1])'''
            #-------------------------------

            weighted_loss = tf.reduce_mean(cross_entropy_loss(o_tokens, dec_result, sample_weight=exp_norm_u_var_distribution))
            #uniform_weighted_loss = tf.reduce_mean(cross_entropy_loss(o_tokens, dec_result))
            focal_loss = sparse_categorical_focal_loss(o_tokens, dec_result, gamma=5)
            #print(focal_loss)
            exp_norm_u_var_distribution = tf.convert_to_tensor(exp_norm_u_var_distribution, dtype=tf.dtypes.float32)
            exp_norm_u_var_distribution = tf.reshape(exp_norm_u_var_distribution, (batch_size, 1))
            #print(exp_norm_u_var_distribution)
            # Class balanced focal loss
            focal_loss *= exp_norm_u_var_distribution

            # topk cross-entropy loss
            topk_cross_entropy_acc = tf.keras.metrics.SparseTopKCategoricalAccuracy(k=len(unique_cls))
            topk_acc = topk_cross_entropy_acc(o_tokens, dec_result, sample_weight=exp_norm_u_var_distribution)
            #print(topk_loss)
            #print(focal_loss)
            step_loss = tf.reduce_mean(focal_loss) + (1.0 - topk_acc)
            #tf.reduce_mean(focal_loss) #+ uniform_weighted_loss #+ 0.5 * uniform_weighted_loss + 0.5 * focal_loss
            #print("----")
            #print(weighted_loss, focal_loss)
            #print("----")
            #focal_loss_func = SparseCategoricalFocalLoss(gamma=10, class_weight=exp_norm_u_var_distribution)
            #step_loss = tf.reduce_mean(sparse_categorical_focal_loss(o_tokens, dec_result, gamma=2)) #focal_loss_func(o_tokens, dec_result)
            loss += step_loss
        '''if t in list(range(free_run_s_index, free_run_s_index + free_run_loops)):
            i_tokens = tf.argmax(dec_result, axis=-1)
        else:
            i_tokens = o_tokens'''
        i_tokens = o_tokens #tf.argmax(dec_result, axis=-1)
    #import sys
    #sys.exit()
    gen_logits = tf.concat(gen_logits, axis=-2)
    loss = loss / seq_len
    #loss_dec_loop_norm = loss_dec_loop_norm / seq_len
    #dec_loop_mean_dist = dec_loop_mean_dist / seq_len
    #dec_loop_norm = dec_loop_norm / seq_len
    #dec_loop_pw_norm = dec_loop_pw_norm / seq_len
    #dec_loop_corr = dec_loop_corr / seq_len
    print("Losses: (true)", loss.numpy())
    #print("Losses: (true, enc norm, dec norm)", loss.numpy(), loss_enc_state_norm.numpy(), loss_dec_loop_norm.numpy()
    #print("Enc state mean dist:", enc_mean_dist)
    #print("Dec state mean dist:", dec_loop_mean_dist)
    #print("Encoder norm: {}".format(str(enc_state_norm)))
    #print("Encoder pairwise dist norm: {}".format(str(enc_pw_norm)))
    #print("Encoder norm with noise: {}".format(str(enc_state_norm_noise)))
    #print("Decoder norm: {}".format(str(dec_loop_norm)))
    #print("Encoder mean correlation: {}".format(str(enc_corr)))
    #print("Decoder mean correlation: {}".format(str(dec_loop_corr)))
    #print("Decoder pairwise dist norm: {}".format(str(dec_loop_pw_norm)))
    #print("--------------")
    #loss = loss + enc_mean_dist + dec_loop_mean_dist + enc_state_norm + dec_loop_norm #+ enc_pw_norm #+ dec_loop_pw_norm
    #loss = loss + enc_mean_dist + dec_loop_mean_dist + enc_state_norm + dec_loop_norm
    #loss = loss + enc_pw_norm + enc_state_norm + dec_loop_norm # + residual_norm + dec_loop_norm
    #loss = loss + enc_state_norm + dec_loop_norm + enc_mean_dist + dec_loop_mean_dist
    #loss = loss + enc_mean_dist + dec_loop_mean_dist # dec_loop_norm
    #loss = loss + enc_corr + dec_loop_corr
    #loss = loss + loss_enc_state_norm + loss_dec_loop_norm
    return gen_logits, gen_encoder, gen_decoder, loss


def loop_encode_decode_predict(seq_len, batch_size, vocab_size, input_tokens, output_tokens, gen_encoder, gen_decoder, enc_units, tf_ratio, train_test, s_stateful, mut_freq): 
    show = 2
    enc_output, enc_state = gen_encoder(input_tokens)
    enc_norm = tf.norm(enc_state)
    dec_state = enc_state
    #print(dec_state)
    #print()
    dec_state = tf.math.add(dec_state, tf.random.normal((dec_state.shape[0], dec_state.shape[1]), stddev=enc_stddev))
    #print(dec_state[:show, :])
    loss = tf.constant(0.0)
    gen_logits = list()
    o_state_norm = list()
    i_tokens = tf.fill([batch_size, 1], 0)
    for t in range(seq_len - 1):
        dec_result, dec_state = gen_decoder([i_tokens, dec_state])
        gen_logits.append(dec_result)
        o_state_norm.append(tf.norm(dec_state))
        dec_state = tf.math.add(dec_state, tf.random.normal((dec_state.shape[0], dec_state.shape[1]), stddev=dec_stddev))
        if len(output_tokens) > 0:
            o_tokens = output_tokens[:, t+1:t+2]
            step_loss = tf.reduce_mean(cross_entropy_loss(o_tokens, dec_result))
            loss += step_loss
        i_tokens = tf.argmax(dec_result, axis=-1)
    gen_logits = tf.concat(gen_logits, axis=-2)
    loss = loss / seq_len
    print("Encoder norm: {}".format(str(tf.norm(enc_state))))
    print("Decoder norm: {}".format(str(np.mean(o_state_norm))))
    #print("--------------")
    return gen_logits, gen_encoder, gen_decoder, loss

def predict_sequence(tr_epoch, tr_batch, test_dataset_in, test_dataset_out, te_batch_size, n_te_batches, seq_len, vocab_size, enc_units, loaded_encoder, loaded_generator, s_stateful, train_type, save=False):
    avg_test_loss = []
    avg_test_seq_var = []
    train_mode = False

    batch_x = list()
    batch_y = list()
    batch_pred = list()
    #for step, (batch_x_test, batch_y_test) in enumerate(zip(test_dataset_in, test_dataset_out)):
    for step in range(n_te_batches):
        batch_x_test, batch_y_test = sample_unrelated_x_y(test_dataset_in, test_dataset_out, te_batch_size)
        # generated noise for variation in predicted sequences
        #noise = tf.random.normal((te_batch_size, enc_units))
        #enc_output, enc_state_h, enc_state_c = loaded_encoder(batch_x_test, training=train_mode)
        #enc_out, enc_state_h, enc_state_c = stateful_encoding(s_stateful, batch_x_test, loaded_encoder, False)
        #loaded_encoder.reset_states()
        #enc_state_h = tf.math.add(enc_state_h, noise)
        #enc_state_c = tf.math.add(enc_state_c, noise)
        #dec_state_h, dec_state_c = enc_state_h, enc_state_c
        #print("Generating sequences for each input sequence...")
        # generate_per_seq(tr_epoch, tr_batch, seq_len, te_batch_size, vocab_size, batch_x_test, batch_y_test, loaded_encoder, loaded_generator, enc_units):
        #generate_per_seq(tr_epoch, tr_batch, seq_len, te_batch_size, vocab_size, batch_x_test, batch_y_test, loaded_encoder, loaded_generator, enc_units)
        #print("Test: true input seq:")
        #print(batch_x_test[:5, 1:])
        #print()
        print("Test: true output seq:")
        print(batch_y_test[:te_batch_size, 1:])
        # generate seqs stepwise - teacher forcing
        #generated_logits, loss = _loop_pred_step(seq_len, te_batch_size, batch_x_test, batch_y_test, loaded_encoder, loaded_generator, enc_units)
        generated_logits, _, _, loss = loop_encode_decode_predict(seq_len, te_batch_size, vocab_size, batch_x_test, batch_y_test, loaded_encoder, loaded_generator, enc_units, test_tf_ratio, train_mode, s_stateful, dict())
        print(tf.argmax(generated_logits, axis=-1)[:te_batch_size, :])
        one_x = convert_to_string_list(batch_x_test)
        one_y = convert_to_string_list(batch_y_test)
        pred_y = convert_to_string_list(tf.math.argmax(generated_logits, axis=-1))
        batch_x.extend(one_x)
        batch_y.extend(one_y)
        batch_pred.extend(pred_y)
        #generated_output_seqs(seq_len, te_batch_size, vocab_size, loaded_generator, dec_state_h, dec_state_c, batch_x_test, batch_y_test, False)  
        variation_score = get_sequence_variation_percentage(batch_x_test, generated_logits)
        #loss = loss + mae([1.0], [variation_score]) #/ variation_score #+ mae([1.0], [variation_score]) #variation_score
        print("Test batch {} variation score: {}".format(str(step+1), str(variation_score)))
        print("Test batch {} true loss: {}".format(str(step+1), str(loss.numpy())))
        print()
        avg_test_loss.append(loss)
        avg_test_seq_var.append(variation_score)
    print()
    print("Total test seq variation in {} batches: {}".format(str(n_te_batches), str(np.mean(avg_test_seq_var))))
    print("Total test loss in {} batches: {}".format(str(n_te_batches), str(np.mean(avg_test_loss))))
    print("---")

    if save is True:
        true_predicted_multiple = pd.DataFrame(list(zip(batch_x, batch_y, batch_pred)), columns=["X", "Y", "Generated"])
        df_path = "{}{}_intermediate_training_prediction_tr_epoch_{}_tr_batch_{}_n_te_batches_{}.csv".format("data/generated_files/", train_type, str(tr_epoch), str(tr_batch), str(step), str(n_te_batches))
        true_predicted_multiple.to_csv(df_path, index=None)
    return np.mean(avg_test_loss), np.mean(avg_test_seq_var)


def generate_per_seq(tr_epoch, tr_batch, seq_len, te_batch_size, vocab_size, batch_x_test, batch_y_test, loaded_encoder, loaded_generator, enc_units):
    test_tf_ratio = 0.0
    train_mode = False
    s_stateful = 10
    generating_fac = 5
    #te_batch_size = 1
    batch_x = list()
    batch_pred = list()
    for index, (in_seq, out_seq) in enumerate(zip(batch_x_test, batch_y_test)):
        for i in range(generating_fac):
            print(in_seq.shape, out_seq.shape, batch_x_test.shape)
            in_seq = in_seq.reshape(1, in_seq.shape[0])
            out_seq = out_seq.reshape(1, out_seq.shape[0])
            #loop_encode_decode(seq_len, te_batch_size, vocab_size, batch_x_test, batch_y_test, loaded_encoder, loaded_generator, enc_units, test_tf_ratio, train_mode, s_stateful, dict())
            generated_logits, _, _, loss = loop_encode_decode(seq_len, te_batch_size, vocab_size, in_seq, out_seq, loaded_encoder, loaded_generator, enc_units, test_tf_ratio, train_mode, s_stateful, dict())
            print(generated_logits)
            one_x = convert_to_string_list(in_seq)
            pred_y = convert_to_string_list(tf.math.argmax(generated_logits, axis=-1))
            batch_x.append(one_x)
            batch_pred.append(pred_y)
    true_predicted_multiple = pd.DataFrame(list(zip(batch_x, batch_pred)), columns=["X", "Generated"])
    df_path = "{}true_predicted_multiple_tr_epoch_{}_tr_batch_{}_te_batch_{}_gen_fac_{}.csv".format("data/generated_files/", str(tr_epoch), str(tr_batch), str(step), str(generating_fac))
    true_predicted_multiple.to_csv(df_path, index=None)


def save_predicted_test_data(test_data_in, test_data_out, te_batch_size, enc_units, vocab_size, epoch_type_name, enc_model_path, dec_model_path):
    te_encoder = tf.keras.models.load_model(enc_model_path)
    te_decoder = tf.keras.models.load_model(dec_model_path)
    test_data_in, test_data_out = convert_to_array(test_data_in), convert_to_array(test_data_out)
    seq_len = test_data_in.shape[1]
    n_te_batches = int(test_data_in.shape[0] / te_batch_size)
    test_tf_ratio = 0.0
    train_mode = False
    s_stateful = True
    test_x = list()
    pred_y = list()
    if n_te_batches > 100:
        n_te_batches = 100
    print("Saving predicted data for test...")
    for b_c in range(n_te_batches):
        s_idx = b_c*te_batch_size
        e_idx = (b_c+1)*te_batch_size
        #print(b_c, s_idx, e_idx)
        batch_x_test, batch_y_test = test_data_in[s_idx:e_idx, :], test_data_out[s_idx:e_idx, :]
        if batch_x_test.shape[0] == te_batch_size:
            #print(batch_x_test.shape, batch_y_test.shape)
            generated_logits, _, _, loss = loop_encode_decode_predict(seq_len, te_batch_size, vocab_size, batch_x_test, batch_y_test, te_encoder, te_decoder, enc_units, test_tf_ratio, train_mode, s_stateful, dict())
            gen_tokens = tf.argmax(generated_logits, axis=-1)
            variation_score = get_sequence_variation_percentage(batch_x_test, generated_logits)
            print("Test batch {}, loss: {},  variation score: {}".format(str(b_c+1), str(loss), str(variation_score)))
            batch_x_test = convert_to_string_list(batch_x_test)
            gen_tokens = convert_to_string_list(gen_tokens)
            test_x.extend(batch_x_test)
            pred_y.extend(gen_tokens)
        else:
            break

    pred_dataframe = pd.DataFrame(list(zip(test_x, pred_y)), columns=["X", "Pred Y"])
    df_filename = "data/generated_files/true_pred_epoch_type_{}.csv".format(epoch_type_name)
    pred_dataframe.to_csv(df_filename, index=None)


def generator_step(seq_len, batch_size, vocab_size, gen_decoder, dec_state_h, dec_state_c, real_i, real_o, train_gen):
    gen_logits = list()
    step_loss = tf.constant(0.0)
    i_token = real_o[:, 0:1]
    for t in tf.range(seq_len - 1):
        new_tokens = real_o[:, t:t+2]
        #i_token, o_token = new_tokens[:, 0:1], new_tokens[:, 1:2]
        dec_result, dec_state_h, dec_state_c = gen_decoder([i_token, dec_state_h, dec_state_c], training=train_gen)
        if len(real_o) > 0:
            o_token = new_tokens[:, 1:2]
            #loss = loss_function(o_token, dec_result)
            loss = cross_entropy_loss(o_token, dec_result)
            step_loss += tf.reduce_mean(loss)
        # randomly select either true output or feed generated output from previous step for forced learning
        if random.random() <= teacher_forcing_ratio:
            #print("True")
            i_token = o_token
        else:
            #print("Generated")
            i_token = tf.argmax(dec_result, axis=-1)
        gen_logits.append(dec_result)
    step_loss = step_loss / float(seq_len)
    pred_logits = tf.concat(gen_logits, axis=-2)
    return pred_logits, gen_decoder, step_loss


def generated_output_seqs(seq_len, batch_size, vocab_size, gen_decoder, dec_state_h, dec_state_c, real_i, real_o, train_gen):
    gen_logits = list()
    step_loss = tf.constant(0.0)
    i_token = tf.fill([batch_size, 1], 0)
    for t in tf.range(seq_len - 1):
        #dec_result, dec_state = gen_decoder([i_token, dec_state], training=train_gen)
        dec_result, dec_state_h, dec_state_c = gen_decoder([i_token, dec_state_h, dec_state_c], training=train_gen)
        gen_logits.append(dec_result)
        if len(real_o) > 0:
            o_token = real_o[:, t+1:t+2]
            #loss = loss_function(o_token, dec_result)
            loss = cross_entropy_loss(o_token, dec_result)
            step_loss += tf.reduce_mean(loss)
        #self feeding
        i_token = tf.argmax(dec_result, axis=-1)
    step_loss = step_loss / float(seq_len)
    pred_logits = tf.concat(gen_logits, axis=-2)
    gen_decoder.reset_states()
    return pred_logits, gen_decoder, step_loss


def balance_train_dataset_by_levenshtein_dist(x, y, x_y_l):
    lst_x = x
    lst_y = y
    l_dist = x_y_l.numpy()
    u_l_dist = list(set(l_dist))
    batch_size = x.shape[0]
    # create more samples, take out samples equal to the number of batch_size
    n_samples = int(batch_size / float(len(u_l_dist))) + 1
    bal_x = list()
    bal_y = list()

    for l_val in u_l_dist:
        l_val_indices = np.where(l_dist == int(l_val))
        len_indices = len(l_val_indices)
        x_rows = np.array(lst_x[l_val_indices])
        y_rows = np.array(lst_y[l_val_indices])
        rand_x_rows = np.array(choices(x_rows, k=n_samples))
        rand_y_rows = np.array(choices(y_rows, k=n_samples))

        bal_x.extend(rand_x_rows)
        bal_y.extend(rand_y_rows)
        print(l_val, len(x_rows), len(y_rows), n_samples, len(rand_x_rows), len(rand_y_rows))

    bal_x = np.array(bal_x)
    bal_y = np.array(bal_y)

    rand_idx = np.random.randint(1, bal_x.shape[0], batch_size)
 
    bal_x_bs = bal_x[rand_idx]
    bal_y_bs = bal_y[rand_idx]

    bal_x_bs = tf.convert_to_tensor(bal_x_bs, dtype=tf.int32)
    bal_y_bs = tf.convert_to_tensor(bal_y_bs, dtype=tf.int32)
    return bal_x_bs, bal_y_bs


def save_batch(batch_x, batch_y, batch_mut_distribution):
    for index, (x, y) in enumerate(zip(batch_x, batch_y)):
        true_x = x.split(",")
        true_y = y.split(",")
        for i in range(len(true_x)):
            first = true_x[i:i+1]
            sec = true_y[i:i+1]
            first_mut = first[0]
            second_mut = sec[0]
            if first_mut != second_mut:
                key = "{}>{}".format(first_mut, second_mut)
                if key not in batch_mut_distribution:
                    batch_mut_distribution[key] = 0
                batch_mut_distribution[key] += 1
    return batch_mut_distribution


def get_mutation_tr_indices(train_in, train_out, kmer_f_dict, kmer_r_dict, f_dict, r_dict, parent_child_pos_vars=dict(), parent_child_pos_vars_count=dict()):
    parent_child_mut_indices = dict()
    #parent_child_pos_vars = dict()
    for index, (x, y) in enumerate(zip(train_in, train_out)):
        true_x = x.split(",")[1:]
        true_y = y.split(",")[1:]
        re_true_x = true_x #reconstruct_seq([kmer_f_dict[pos] for pos in true_x])
        re_true_y = true_y #reconstruct_seq([kmer_f_dict[pos] for pos in true_y])
        for i in range(len(true_x)):
            first = re_true_x[i:i+1][0]
            sec = re_true_y[i:i+1][0]
            if first != sec:
                key = "{}>{}>{}".format(first, (i+1), sec)
                if key not in parent_child_mut_indices:
                    parent_child_mut_indices[key] = list()
                parent_child_mut_indices[key].append(index)
            key_pos_var = "{}".format(str(i))
            if key_pos_var not in parent_child_pos_vars:
                parent_child_pos_vars[key_pos_var] = list()
                parent_child_pos_vars_count[key_pos_var] = dict()

            if int(sec) not in parent_child_pos_vars[key_pos_var]:
                parent_child_pos_vars[key_pos_var].append(int(sec))

            if int(sec) not in parent_child_pos_vars_count[key_pos_var]:
                parent_child_pos_vars_count[key_pos_var][int(sec)] = 0
            parent_child_pos_vars_count[key_pos_var][int(sec)] += 1
    save_as_json("data/generated_files/parent_child_pos_vars_{}.txt".format(str(np.random.randint(0, 1e10, 1)[0])), parent_child_pos_vars)
    save_as_json("data/generated_files/parent_child_pos_vars_count_{}.txt".format(str(np.random.randint(0, 1e10, 1)[0])), parent_child_pos_vars_count)
    return parent_child_mut_indices, parent_child_pos_vars, parent_child_pos_vars_count


'''
def evaluate_sequence(test_dataset_in, test_dataset_out, te_batch_size, n_te_batches, seq_len, vocab_size, enc_units, loaded_encoder, loaded_decoder):
  
  for step in range(n_te_batches):
        batch_x_test, batch_y_test = sample_unrelated_x_y(test_dataset_in, test_dataset_out, te_batch_size)
        enc_start_state = [tf.zeros((te_batch_size, enc_units)), tf.zeros((te_batch_size, enc_units))]

        print(batch_x_test.shape)

        enc_out, enc_h, enc_c = loaded_encoder(batch_x_test, enc_start_state)

        print(enc_out.shape)

        dec_h = enc_h
        dec_c = enc_c

        start_tokens = tf.fill([te_batch_size], 0)

        greedy_sampler = tfa.seq2seq.GreedyEmbeddingSampler()

        print(greedy_sampler)

        # Instantiate BasicDecoder object
        decoder_instance = tfa.seq2seq.BasicDecoder(cell=loaded_decoder.rnn_cell, sampler=greedy_sampler, output_layer=loaded_decoder.fc)

        print(decoder_instance)
        # Setup Memory in decoder stack
        loaded_decoder.attention_mechanism.setup_memory(enc_out)

        # set decoder_initial_state
        decoder_initial_state = loaded_decoder.build_initial_state(te_batch_size, [enc_h, enc_c], tf.float32)

        print(decoder_initial_state)
        ### Since the BasicDecoder wraps around Decoder's rnn cell only, you have to ensure that the inputs to BasicDecoder 
        ### decoding step is output of embedding layer. tfa.seq2seq.GreedyEmbeddingSampler() takes care of this. 
        ### You only need to get the weights of embedding layer, which can be done by decoder.embedding.variables[0] and pass this callabble to BasicDecoder's call() function

        decoder_embedding_matrix = loaded_decoder.embedding.variables[0]
        print(decoder_embedding_matrix.shape)

        outputs, _, _ = decoder_instance(decoder_embedding_matrix, start_tokens = start_tokens, end_token=vocab_size-2, initial_state=decoder_initial_state)
        print(outputs, dir(outputs))

        loaded_decoder.attention_mechanism.setup_memory(enc_out)
        decoder_initial_state = gen_decoder.build_initial_state(batch_size, [enc_h, enc_c], tf.float32)
        
        pred = gen_decoder(, decoder_initial_state)
        gen_logits = pred.rnn_output
        gen_loss = loss_function(unrolled_y, gen_logits)

        #return outputs.sample_id.numpy()

def translate(sentence):
  result = evaluate_sentence(sentence)
  print(result)
  result = targ_lang.sequences_to_texts(result)
  print('Input: %s' % (sentence))
  print('Predicted translation: {}'.format(result))


'''

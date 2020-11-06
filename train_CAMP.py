from keras.layers import *
from keras.models import *
from keras.optimizers import rmsprop
import tensorflow as tf
from keras.backend.tensorflow_backend import set_session
from  Self_Attention import *
import math, sys, sklearn, pickle
import numpy as np
import argparse as ap
from sklearn.model_selection import StratifiedKFold
from sklearn.cross_validation import KFold

from camp_utils import *



def get_session(gpu_fraction=0.9):
	config = tf.ConfigProto()
	config.gpu_options.per_process_gpu_memory_fraction = gpu_fraction
	return tf.Session(config=config)

set_session(get_session())


def binding_vec_pos(bs_str,N):
	if bs_str == 'NoBinding':
		print('Error! This record is positive.')
		return None
	if bs_str == '-99999':
		bs_vec = np.zeros(N)
		bs_vec.fill(-99999)
                return bs_vec
	else:
		bs_list = [int(x) for x in bs_str.split(',')]
		bs_list = [x for x in bs_list if x<N]
		bs_vec = np.zeros(N)
		bs_vec[bs_list]=1

		return bs_vec

def binding_vec_neg(bs_str,N):
	if bs_str!= 'NoBinding':
		print('Error! This record is negative.')
		return None
	else :
		bs_vec = np.zeros(N)
		return bs_vec


def get_mask(protein_seq,pad_seq_len):
	if len(protein_seq)<=pad_seq_len:
		a = np.zeros(pad_seq_len)
		a[:len(protein_seq)] = 1
	else:
		cut_protein_seq = protein_seq[:pad_seq_len]
		a = np.zeros(pad_seq_len)
		a[:len(cut_protein_seq)] = 1
	return a


# flag is an indicator for checking whether this record has binding sites information
def boost_mask_BCE_loss(input_mask,flag):
	def conditional_BCE(y_true, y_pred):
                loss = flag * K.binary_crossentropy(y_true, y_pred) * input_mask
		return K.sum(loss) / K.sum(input_mask)
	return conditional_BCE


def CAMP_model(NUM_FILTERS, PEP_KERNEL_SIZE, PROT_KERNEL_SIZE):
   
    peptide_input = Input(shape=(pad_pep_len,), dtype='int32')
    protein_input = Input(shape=(pad_seq_len,), dtype='int32')

    peptide_ss_input = Input(shape=(max_smi_ss_len,), dtype='int32')
    protein_ss_input = Input(shape=(max_seq_ss_len,), dtype='int32')

    pep_phy_input = Input(shape=(pad_pep_len,), dtype='int32')
    prot_phy_input = Input(shape=(pad_seq_len,), dtype='int32')

    pep_dense_input = Input(shape=(pad_pep_len,3), dtype='float32')
    prot_dense_input = Input(shape=(pad_seq_len,23), dtype='float32')
    pep_mask_input = Input(shape=(pad_pep_len,), dtype='float32')
    pep_flag_input = Input(shape=(1,), dtype='float32')

    # Dense Feature
    dense_peptide = Dense(128)(pep_dense_input)
    dense_protein = Dense(128)(prot_dense_input)

    # peptide embedding  module
    pep_var_init = Embedding(input_dim=charsmiset_size+1, output_dim=128, input_length=pad_pep_len)(peptide_input)
    pep_var_ss = Embedding(input_dim=protein_vocab_size+1, output_dim=128, input_length=max_smi_ss_len)(peptide_ss_input)
    pep_var_two = Embedding(input_dim=property_vocab_size+1, output_dim=128, input_length=pad_pep_len)(pep_phy_input)

    pep_var = keras.layers.concatenate([pep_var_init,pep_var_ss,pep_var_two,dense_peptide], axis=-1)

    # peptide convolution module 
    pep_var = Conv1D(filters=NUM_FILTERS, kernel_size=PEP_KERNEL_SIZE,  activation='relu', padding='same',  strides=1)(pep_var)
    pep_var = Conv1D(filters=NUM_FILTERS*2, kernel_size=PEP_KERNEL_SIZE,  activation='relu', padding='same',  strides=1)(pep_var)
    pep_var = Conv1D(filters=NUM_FILTERS*3, kernel_size=PEP_KERNEL_SIZE,  activation='relu', padding='same',  strides=1)(pep_var)
    pep_var_global = GlobalMaxPooling1D()(pep_var)

    # peptide binding site module
    nn_prob_peptide = TimeDistributed(Dense(1,kernel_initializer='normal', activation='sigmoid'))(pep_var)
    nn_prob_peptide = Lambda(lambda x: K.squeeze(x, axis=-1), name = 'nn_prob_peptide')(nn_prob_peptide)

    # protein embedding module
    prot_var_init = Embedding(input_dim=protein_vocab_size+1, output_dim=128, input_length=pad_seq_len)(protein_input)
    prot_var_ss = Embedding(input_dim=protein_vocab_size+1, output_dim=128, input_length=max_seq_ss_len)(protein_ss_input)
    prot_var_two = Embedding(input_dim=property_vocab_size+1, output_dim=128, input_length=pad_seq_len)(prot_phy_input)

    prot_var = keras.layers.concatenate([prot_var_init,prot_var_ss,prot_var_two,dense_protein], axis=-1)

    # protein convolution module
    prot_var = Conv1D(filters=NUM_FILTERS, kernel_size=PROT_KERNEL_SIZE,  activation='relu', padding='same',  strides=1)(prot_var)
    prot_var = Conv1D(filters=NUM_FILTERS*2, kernel_size=PROT_KERNEL_SIZE,  activation='relu', padding='same',  strides=1)(prot_var)
    prot_var = Conv1D(filters=NUM_FILTERS*3, kernel_size=PROT_KERNEL_SIZE,  activation='relu', padding='same',  strides=1)(prot_var)
    prot_var_global = GlobalMaxPooling1D()(prot_var)

    # protein self-attenetion
    protein_att = Self_Attention(128)(prot_var_init)
    protein_att = GlobalMaxPooling1D()(protein_att)

    # peptide self-attention
    peptide_att = Self_Attention(128)(prot_var_init)
    peptide_att = GlobalMaxPooling1D()(peptide_att)

    # binary prediction module
    binary_var = keras.layers.concatenate([pep_var_global,prot_var_global,protein_att,peptide_att], axis=-1)
    fc_binary = Dense(1024, activation='relu')(binary_var)
    fc_binary = Dropout(0.1)(fc_binary)
    fc_binary = Dense(1024, activation='relu')(fc_binary)
    fc_binary = Dropout(0.1)(fc_binary)
    fc_binary = Dense(512, activation='relu')(fc_binary)
    predictions = Dense(1, kernel_initializer='normal', activation='sigmoid',name='predictions')(fc_binary) 
    CAMP = Model(inputs=[peptide_input, protein_input, peptide_ss_input, protein_ss_input, pep_phy_input, prot_phy_input, pep_dense_input, prot_dense_input,pep_mask_input,pep_flag_input], outputs=[predictions,nn_prob_peptide])
    optimizer = keras.optimizers.rmsprop(lr=0.0005, decay=1e-6)

    CAMP.compile(optimizer=optimizer, loss = {'predictions': 'binary_crossentropy', 'nn_prob_peptide': boost_mask_BCE_loss(pep_mask_input,pep_flag_input)},\
    	loss_weights = {'predictions':1.0, 'nn_prob_peptide':10})

    return CAMP


def train(train_data, valid_data, test_data, n_epoch=100):
	model = CAMP_model(num_windows, smi_window_lengths, prot_kernel_size)

	train_pep, train_prot, train_pep_ss, train_prot_ss train_pep_phy, train_prot_phy, train_pep_dense, train_prot_dense,train_pssm, train_Y, train_pep_mask, train_Y_pep_bs, train_bs_flag = train_data
	valid_pep, valid_prot, valid_pep_ss, valid_prot_ss, valid_pep_phy, valid_prot_phy,valid_pep_dense, valid_prot_dense,valid_pssm, valid_Y, valid_pep_mask,valid_Y_pep_bs, valid_bs_flag = valid_data
	test_pep, test_prot, test_pep_ss, test_prot_ss, test_pep_phy, test_prot_phy, test_pep_dense, test_prot_dense, test_pssm, test_Y, test_pep_mask,test_Y_pep_bs, test_bs_flag = test_data
	
	for e in range(n_epoch):

		CAMP = model.fit(([np.array(train_pep),np.array(train_prot),np.array(train_pep_ss),np.array(train_prot_ss),\
							  np.array(train_pep_phy),np.array(train_prot_phy),np.array(train_pep_dense),np.array(train_prot_dense),\
							  np.array(train_pep_mask),np.array(train_bs_flag)]),\
		{'predictions':np.array(train_Y), 'nn_prob_peptide':np.array(train_Y_pep_bs)}, batch_size=batch_size, epochs=1)

		pred_train = model.predict([np.array(train_pep),np.array(train_prot),np.array(train_pep_ss),np.array(train_prot_ss),\
									np.array(train_pep_phy),np.array(train_prot_phy),np.array(train_pep_dense),np.array(train_prot_dense),\
									np.array(train_pep_mask),np.array(train_bs_flag)],batch_size=batch_size)[0]
		pred_valid = model.predict([np.array(valid_pep),np.array(valid_prot),np.array(valid_pep_ss),np.array(valid_prot_ss),\
									np.array(valid_pep_phy),np.array(valid_prot_phy),np.array(valid_pep_dense),np.array(valid_prot_dense),\
									np.array(valid_pep_mask),np.array(valid_bs_flag)],batch_size=batch_size)[0]
		train_scores = auc_aupr(train_Y, pred_train)
		valid_scores = auc_aupr(valid_Y, pred_valid)

		#if valid_scores[0] < min_rmse:
		#min_rmse = valid_scores[0]
		pred_test = model.predict([np.array(test_pep),np.array(test_prot),np.array(test_pep_ss),np.array(test_prot_ss),\
									np.array(test_pep_phy),np.array(test_prot_phy),np.array(test_pep_dense),np.array(test_prot_dense),\
									np.array(test_pep_mask),np.array(test__bs_flag)],batch_size=batch_size)[0]
		pred_test_d_bs = model.predict([np.array(test_pep),np.array(test_prot),np.array(test_pep_ss),np.array(test_prot_ss),\
				np.array(test_pep_phy),np.array(test_prot_phy),np.array(test_pep_dense),np.array(test_prot_dense),\
				np.array(test_pep_mask),np.array(test__bs_flag)],batch_size=batch_size)[1]


		test_scores = auc_aupr(test_Y, pred_test)
		print('train', len(pred_train), 'auc', round(train_scores[0],4), 'aupr', round(train_scores[1],4))
		print('valid', len(pred_valid), 'auc', round(valid_scores[0],4), 'aupr', round(valid_scores[1],4))
		print('test', len(pred_test),  'auc', round(test_scores[0],4), 'aupr', round(test_scores[1],4)) 

	return pred_train, pred_valid, pred_test, pred_test_d_bs, model



def load(name):
	print('loading feature:'), name
	
	with open('./preprocessing_v2/'+task+'_'+name+'_protein_feature_dict') as f: 
		protein_feature_dict = pickle.load(f)
	with open('./preprocessing_v2/'+task+'_'+name+'_peptide_feature_dict') as f:
		peptide_feature_dict = pickle.load(f)
	with open('./preprocessing_v2/'+task+'_'+name+'_protein_ss_feature_dict') as f: 
		protein_ss_feature_dict = pickle.load(f)
	with open('./preprocessing_v2/'+task+'_'+name+'_peptide_ss_feature_dict') as f:
		peptide_ss_feature_dict = pickle.load(f)
	with open('./preprocessing_v2/'+task+'_'+name+'_protein_2_feature_dict') as f: 
		protein_2_feature_dict = pickle.load(f)
	with open('./preprocessing_v2/'+task+'_'+name+'_peptide_2_feature_dict') as f:
		peptide_2_feature_dict = pickle.load(f)
	with open('./preprocessing_v2/'+task+'_'+name+'_protein_dense_feature_dict') as f: 
		protein_dense_feature_dict = pickle.load(f)
	with open('./preprocessing_v2/'+task+'_'+name+'_peptide_dense_feature_dict') as f:
		peptide_dense_feature_dict = pickle.load(f)
	with open('./preprocessing_v2/'+task+'_'+name+'_protein_pssm_feature_dict') as f: 
		protein_pssm_feature_dict = pickle.load(f)


	
	datafile = input_file
	print('load features of peptides and proteins')
	X_pep, X_prot, X_pep_ss, X_SS_p, X_pep_phy, X_prot_phy = [], [], [], [], [], []
	X_pep_dense,X_prot_dense,X_pssm = [],[],[]
	peptide_sequence, protein_sequence, Y = [], [], []
	Y_pep_bs, X_pep_mask, X_bs_flag = [], [], []
	with open(datafile) as f:
		for line in f.readlines()[1:]:
			seq, peptide, label, smiles_ss, seq_ss, pep_bs  = line.strip().split('\t')
			if int(label)==1:
				pep_bs_vec = binding_vec_pos(pep_bs,pad_pep_len)
				if pep_bs == '-99999':
					flag =0.0
				else : 
					flag =1.0
			if int(label)==0:
				flag=0.0
				pep_bs_vec = binding_vec_neg(pep_bs,pad_pep_len)

			X_pep_mask.append(get_mask(peptide,pad_pep_len))
			Y_pep_bs.append(pep_bs_vec)
			X_bs_flag.append(flag)

			peptide_sequence.append(peptide)
			protein_sequence.append(seq)
			Y.append(label)
			X_pep.append(peptide_feature_dict[peptide])
			X_prot.append(protein_feature_dict[seq])
			X_pep_ss.append(peptide_ss_feature_dict[smiles_ss])
			X_SS_p.append(protein_ss_feature_dict[seq_ss])
			X_pep_phy.append(peptide_2_feature_dict[peptide])
			X_prot_phy.append(protein_2_feature_dict[seq])
			X_pep_dense.append(peptide_dense_feature_dict[peptide])
			X_prot_dense.append(protein_dense_feature_dict[seq])
			X_pssm.append(protein_pssm_feature_dict[seq])

			
	X_pep = np.array(X_pep)
	X_prot = np.array(X_prot)
	X_pep_ss = np.array(X_pep_ss)
	X_SS_p = np.array(X_SS_p)
	X_pep_phy = np.array(X_pep_phy)
	X_prot_phy = np.array(X_prot_phy)
	X_pep_dense = np.array(X_pep_dense)
	X_prot_dense = np.array(X_prot_dense)
	X_pssm = np.array(X_pssm)
	Y = np.array(Y).astype(int)

	X_pep_mask = np.array(X_pep_mask)
	Y_pep_bs = np.array(Y_pep_bs)
	X_bs_flag = np.array(X_bs_flag)

	peptide_sequence = np.array(peptide_sequence)
	protein_sequence = np.array(protein_sequence)
	train_idx = range(Y.shape[0])
	np.random.shuffle(train_idx)
	X_pep = X_pep[train_idx]
	X_prot = X_prot[train_idx]
	X_pep_ss = X_pep_ss[train_idx]
	X_SS_p = X_SS_p[train_idx]
	X_protOL_c = X_protOL_c[train_idx]
	X_protOL_p = X_protOL_p[train_idx]
	X_HYD_c = X_HYD_c[train_idx]
	X_HYD_p = X_HYD_p[train_idx]
	X_pep_phy = X_pep_phy[train_idx]
	X_prot_phy = X_prot_phy[train_idx]
	X_pep_dense = X_pep_dense[train_idx]
	X_prot_dense = X_prot_dense[train_idx]
	X_pssm = X_pssm[train_idx]
	X_intrinsic_p = X_intrinsic_p[train_idx]
	Y = Y[train_idx]

	X_pep_mask = X_pep_mask[train_idx]
	X_bs_flag = X_bs_flag[train_idx]
	Y_pep_bs = Y_pep_bs[train_idx]
	
	peptide_sequence = peptide_sequence[train_idx]
	protein_sequence = protein_sequence[train_idx]
	
	return X_pep, X_prot, X_pep_ss, X_SS_p, X_pep_phy, X_prot_phy, , X_prot_dense, , Y, peptide_sequence, protein_sequence, X_pep_mask, Y_pep_bs, X_bs_flag


def random_split(X_pep, X_prot, Y, fold=5):
	skf = StratifiedKFold(n_splits=fold, shuffle=True)
	train_idx_list, valid_idx_list, test_idx_list = [], [], []
	for train_index, test_index in skf.split(X_pep, Y):
		train_idx_list.append(train_index)
		valid_idx_list.append(np.random.choice(train_index, len(train_index)/10, replace=False))
		test_idx_list.append(test_index)
	return train_idx_list, valid_idx_list, test_idx_list


single_result_list, all_results_list = [], []

X_pep, X_prot, X_pep_ss, X_SS_p, X_pep_phy, X_prot_phy, X_pep_dense, X_prot_dense, X_pssm, Y, peptide_sequence, protein_sequence, X_pep_mask, Y_pep_bs, X_bs_flag = load(name)
train_idx_list, valid_idx_list, test_idx_list = random_split(X_pep, X_prot, Y, fold=5)
train_score_list, valid_score_list, test_score_list = [], [], []


if __name__ == '__main__':
    input_file = sys.argv[1]

    batch_size = 256
	n_fold = 5
	n_epoch = 100
	pad_pep_len = 50
	pad_seq_len = int(np.load('./preprocessing/pad_seq_len.npy'))
	protein_vocab_size = 21
	property_vocab_size = 7
	num_filters = 64
	prot_kernel_size = 9 
	pep_kernel_size = 7 


	for fold in range(n_fold):
		print('fold', fold+1, 'begin training')
		train_ind, valid_ind, test_ind = train_idx_list[fold], valid_idx_list[fold], test_idx_list[fold]
		print('training set size: ',len(train_ind),'testing set size set: ',len(test_ind),'valid set size: ',len(valid_ind))

		train_pep, train_prot, train_pep_ss, train_prot_ss, train_pep_phy, train_prot_phy, \
			train_pep_dense, train_prot_dense,train_pssm, train_Y, train_pep_mask, train_Y_pep_bs, train_bs_flag  = \
				X_pep[train_ind], X_prot[train_ind], X_pep_ss[train_ind], X_SS_p[train_ind], X_pep_phy[train_ind], X_prot_phy[train_ind], \
				X_pep_dense[train_ind], X_prot_dense[train_ind], X_pssm[train_ind], Y[train_ind],\
				X_pep_mask[train_ind], Y_pep_bs[train_ind],X_bs_flag[train_ind]
		
		valid_pep, valid_prot, valid_pep_ss, valid_prot_ss, valid_pep_phy, valid_prot_phy, \
			valid_pep_dense, valid_prot_dense,valid_pssm, valid_Y, valid_pep_mask, valid_Y_pep_bs, valid_bs_flag  = \
				X_pep[valid_ind], X_prot[valid_ind], X_pep_ss[valid_ind], X_SS_p[valid_ind], X_pep_phy[valid_ind], X_prot_phy[valid_ind], \
				X_pep_dense[valid_ind], X_prot_dense[valid_ind], X_pssm[valid_ind], Y[valid_ind],\
				X_pep_mask[valid_ind], Y_pep_bs[valid_ind], X_bs_flag[valid_ind]
		
		test_pep, test_prot, test_pep_ss, test_prot_ss, test_pep_phy, test_prot_phy, \
			test_pep_dense, test_prot_dense,test_pssm, test_Y, test_pep_mask, test_Y_pep_bs, test_bs_flag  = \
				X_pep[test_ind], X_prot[test_ind], X_pep_ss[test_ind], X_SS_p[test_ind],  X_pep_phy[test_ind], X_prot_phy[test_ind], \
				X_pep_dense[test_ind], X_prot_dense[test_ind], X_pssm[test_ind], Y[test_ind],\
				X_pep_mask[test_ind], Y_pep_bs[test_ind], X_bs_flag[test_ind]
		
		
		train_data = train_pep, train_prot, train_pep_ss, train_prot_ss, train_pep_phy, train_prot_phy, \
						train_pep_dense, train_prot_dense,train_pssm, train_Y, train_pep_mask, train_Y_pep_bs, train_bs_flag
		valid_data = valid_pep, valid_prot, valid_pep_ss, valid_prot_ss, valid_pep_phy, valid_prot_phy, \
						valid_pep_dense, valid_prot_dense,valid_pssm, valid_Y, valid_pep_mask, valid_Y_pep_bs, valid_bs_flag
		test_data = test_pep, test_prot, test_pep_ss, test_prot_ss, test_pep_phy, test_prot_phy, \
						test_pep_dense, test_prot_dense, test_pssm, test_Y, test_pep_mask, test_Y_pep_bs, test_bs_flag


		test_peptide = peptide_sequence[test_ind]
		test_protein = protein_sequence[test_ind]
		
		pred_train, pred_valid, pred_test, pred_test_d_bs, model = train(train_data, valid_data, test_data, n_epoch)

		train_scores = auc_aupr(train_Y, pred_train)
		valid_scores = auc_aupr(valid_Y, pred_valid)
		test_scores = auc_aupr(test_Y, pred_test)
		train_score_list.append(train_scores)
		valid_score_list.append(valid_scores)
		test_score_list.append(test_scores)
		print ('train set', len(pred_train), 'AUC', round(train_scores[0],4), 'AUPR', round(train_scores[1],4))
		print ('valid set', len(pred_valid), 'AUC', round(valid_scores[0],4), 'AUPR', round(valid_scores[1],4))
		print ('test set', len(pred_test),  'AUC', round(test_scores[0],4), 'AUPR', round(test_scores[1],4))
		all_results_list.append(test_scores)
	single_result_list.append(np.mean(test_score_list,axis=0))

	print('finish cross validation')

	print('==============')
	print('the mean of AUC & AUPR', np.mean(all_results_list, axis=0))
	print('the standard deviation of AUC & AUPR', np.std(all_results_list, axis=0))


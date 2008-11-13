"""
 Connection method classes for nest
 $Id: connectors.py 468 2008-10-03 22:21:06Z apdavison $
"""

from pyNN import common
from pyNN.nest2.__init__ import nest, is_number, get_max_delay, get_min_delay
import numpy
# note that WDManager is defined in __init__.py imported here, then imported
# into __init__ through `from connectors import *`. This circularity can't be a
# good thing. Better to define WDManager here?
from pyNN.random import RandomDistribution, NativeRNG
from math import *
from random import sample
from numpy import arccos, arcsin, arctan, arctan2, ceil, cos, cosh, e, exp, \
                  fabs, floor, fmod, hypot, ldexp, log, log10, modf, pi, power, \
                  sin, sinh, sqrt, tan, tanh

CHECK_CONNECTIONS = True

class InvalidWeightError(Exception): pass

def _convertWeight(w, synapse_type):
    weight = w*1000.0
    if isinstance(w, numpy.ndarray):
        all_negative = (weight<=0).all()
        all_positive = (weight>=0).all()
        if not (all_negative or all_positive):
            raise InvalidWeightError("Weights must be either all positive or all negative")
        if synapse_type == 'inhibitory' and all_positive:
            weight *= -1
        elif synapse_type == 'excitatory':
            if not all_positive:
                raise InvalidWeightError("Weights must be positive for excitatory synapses")
    elif is_number(weight):
        if synapse_type == 'inhibitory' and weight > 0:
            weight *= -1
        elif synapse_type == 'excitatory':
            if weight < 0:
                raise InvalidWeightError("Weight must be positive for excitatory synapses. Actual value %s" % weight)
    else:
        raise TypeError("weight must be either a number or a numpy array")
    return weight

def check_connections(prj, src, intended_targets):
    conn_dict = nest.GetConnections([src], prj.plasticity_name)[0]
    if isinstance(conn_dict, dict):
        N = len(intended_targets)
        all_targets = conn_dict['targets']
        actual_targets = all_targets[-N:]
        assert actual_targets == intended_targets, "%s != %s" % (actual_targets, intended_targets)
    else:
        raise Exception("Problem getting connections for %s" % pre)

class AllToAllConnector(common.AllToAllConnector):    

    def connect(self, projection):
        postsynaptic_neurons  = projection.post.cell_local.flatten()
        target_list = postsynaptic_neurons.tolist()
        for pre in projection.pre.cell.flat:
            # if self connections are not allowed, check whether pre and post are the same
            if not self.allow_self_connections:
                target_list = postsynaptic_neurons.tolist()
                if pre in target_list:
                    target_list.remove(pre)
            N = len(target_list)
            weights = self.getWeights(N)
            weights = _convertWeight(weights, projection.synapse_type).tolist()
            delays = self.getDelays(N).tolist()
            projection._targets += target_list
            projection._sources += [pre]*N
            nest.DivergentConnectWD([pre], target_list, weights, delays)
            if CHECK_CONNECTIONS:
                check_connections(projection, pre, target_list)
        return len(projection._targets)

class OneToOneConnector(common.OneToOneConnector):
    
    def connect(self, projection):
        if projection.pre.dim == projection.post.dim:
            projection._sources = projection.pre.cell.flatten()
            projection._targets = projection.post.cell.flatten()
            N = len(projection._sources)
            weights = self.getWeights(N)
            weights = _convertWeight(weights, projection.synapse_type).tolist()
            delays = self.getDelays(N).tolist()
            nest.ConnectWD(projection._sources, projection._targets, weights, delays)
            return projection.pre.size
        else:
            raise common.InvalidDimensionsError("OneToOneConnector does not support presynaptic and postsynaptic Populations of different sizes.")
    
class FixedProbabilityConnector(common.FixedProbabilityConnector):
    
    def connect(self, projection):
        postsynaptic_neurons = projection.post.cell_local
        npost = len(postsynaptic_neurons)
        if projection.rng:
            if isinstance(projection.rng, NativeRNG):
                print "Warning: use of NativeRNG not implemented. Using NumpyRNG"
                rng = numpy.random
            else:
                rng = projection.rng
        else:
            rng = numpy.random
        for pre in projection.pre.cell.flat:
            rarr = rng.uniform(0, 1, npost) # what about NativeRNG?
            target_list = numpy.compress(numpy.less(rarr, self.p_connect), postsynaptic_neurons).tolist()
            #N           = rng.binomial(npost,self.p_connect,1)[0]
            #target_list = sample(postsynaptic_neurons, N)
            # if self connections are not allowed, check whether pre and post are the same
            if not self.allow_self_connections and pre in target_list:
                target_list.remove(pre)
            N = len(target_list)
            weights = self.getWeights(N)
            weights = _convertWeight(weights, projection.synapse_type).tolist()
            delays  = self.getDelays(N).tolist()
            projection._targets += target_list
            projection._sources += [pre]*N
            nest.DivergentConnectWD([pre], target_list, weights, delays)
            if CHECK_CONNECTIONS:
                check_connections(projection, pre, target_list)
        return len(projection._sources)
    
class DistanceDependentProbabilityConnector(common.DistanceDependentProbabilityConnector):
    
    def connect(self, projection):
        periodic_boundaries = self.periodic_boundaries
        if periodic_boundaries is True:
            dimensions = projection.post.dim
            periodic_boundaries = tuple(numpy.concatenate((dimensions, numpy.zeros(3-len(dimensions)))))
        if periodic_boundaries:
            print "Periodic boundaries activated and set to size ", periodic_boundaries
        postsynaptic_neurons = projection.post.cell.flatten() # array
        npost = len(postsynaptic_neurons)
        #postsynaptic_neurons = projection.post.cell_local
        # what about NativeRNG?
        if projection.rng:
            if isinstance(projection.rng, NativeRNG):
                print "Warning: use of NativeRNG not implemented. Using NumpyRNG"
                rng = numpy.random
            else:
                rng = projection.rng
        else:
            rng = numpy.random
            
        get_proba   = lambda d: eval(self.d_expression)
        get_weights = lambda d: eval(self.weights)
        get_delays  = lambda d: eval(self.delays)
            
        for pre in projection.pre.cell.flat:
            # We compute the distances from the post cell to all the others
            distances = common.distances(pre, projection.post, self.mask,
                                         self.scale_factor, self.offset,
                                         periodic_boundaries)[0]
            # We evaluate the probabilities of connections for those distances
            proba = get_proba(distances)
            # We get the list of cells that will established a connection
            rarr = rng.uniform(0, 1, (npost,))
            idx = numpy.where((proba >= 1) | ((0 < proba) & (proba < 1) & (rarr <= proba)))[0]
            target_list = postsynaptic_neurons[idx].tolist()
            # We remove the pre cell if we don't allow self connections
            if not self.allow_self_connections and pre in target_list:
                idx.remove(target_list.index(pre))
                target_list.remove(pre)
            N = len(target_list)
            # We deal with the fact that the user could have given a weights distance dependent
            if isinstance(self.weights,str):
                weights = get_weights(distances[idx])
            else:
                weights = self.getWeights(N)
            weights = _convertWeight(weights, projection.synapse_type).tolist()
            # We deal with the fact that the user could have given a delays distance dependent
            if isinstance(self.delays,str):
                delays = get_delays(distances[idx]).tolist()
            else:
                delays = self.getDelays(N).tolist()
            projection._targets += target_list
            projection._sources += [pre]*N 
            nest.DivergentConnectWD([pre], target_list, weights, delays)
            if CHECK_CONNECTIONS:
                check_connections(projection, pre, target_list)
        return len(projection._sources)

class FixedNumberPostConnector(common.FixedNumberPostConnector):
    
    def connect(self, projection):
        postsynaptic_neurons  = projection.post.cell.flatten()
        if projection.rng:
            rng = projection.rng
        else:
            rng = numpy.random
        for pre in projection.pre.cell.flat:
            if hasattr(self, 'rand_distr'):
                n = self.rand_distr.next()
            else:
                n = self.n
                assert n > 0
                
            if not self.allow_self_connections and projection.pre == projection.post:
                # if self connections are not allowed, remove `post` from the target list before picking the n values
                tmp_postsyn = postsynaptic_neurons.tolist()
                tmp_postsyn.remove(pre)
                target_list = rng.permutation(tmp_postsyn)[0:n].tolist()   
            else:
                target_list = rng.permutation(postsynaptic_neurons)[0:n].tolist()

            N = len(target_list)
            weights = self.getWeights(N)
            weights = _convertWeight(weights, projection.synapse_type).tolist()
            delays = self.getDelays(N).tolist()
            nest.DivergentConnectWD([pre], target_list, weights, delays)
            projection._sources += [pre]*N
            projection._targets += target_list
            if CHECK_CONNECTIONS:
                check_connections(projection, pre, target_list)
        return len(projection._sources)


class FixedNumberPreConnector(common.FixedNumberPreConnector):
    
    def connect(self, projection):
        presynaptic_neurons = projection.pre.cell.flatten()
        if projection.rng:
            rng = projection.rng
        else:
            rng = numpy.random
        for post in projection.post.cell.flat:
            if hasattr(self, 'rand_distr'):
                n = self.rand_distr.next()
            else:
                n = self.n
                
            if not self.allow_self_connections and projection.pre == projection.post:
                # if self connections are not allowed, remove `post` from the source list before picking the n values
                tmp_presyn = presynaptic_neurons.tolist()
                tmp_presyn.remove(post)
                source_list = rng.permutation(tmp_presyn)[0:n].tolist()    
            else:
                source_list = rng.permutation(presynaptic_neurons)[0:n].tolist()
            
            N = len(source_list)
            weights = self.getWeights(N)
            weights = _convertWeight(weights, projection.synapse_type).tolist()
            delays = self.getDelays(N).tolist()

            nest.ConvergentConnectWD(source_list, [post],
                                     weights, delays)
            if CHECK_CONNECTIONS:
                for src in source_list:
                    check_connections(projection, src, [post])
            projection._sources += source_list
            projection._targets += [post]*N

        return len(projection._sources)


def _connect_from_list(conn_list, projection):
    # slow: should maybe sort by pre and use DivergentConnect?
    # or at least convert everything to a numpy array at the start
    weights = []; delays = []
    for i in xrange(len(conn_list)):
        src, tgt, weight, delay = conn_list[i][:]
        src = projection.pre[tuple(src)]
        tgt = projection.post[tuple(tgt)]
        projection._sources.append(src)
        projection._targets.append(tgt)
        weights.append(_convertWeight(weight, projection.synapse_type))
        delays.append(delay)
    nest.ConnectWD(projection._sources, projection._targets, weights, delays)
    return projection.pre.size


class FromListConnector(common.FromListConnector):
    
    def connect(self, projection):
        return _connect_from_list(self.conn_list, projection)


class FromFileConnector(common.FromFileConnector):
    
    def connect(self, projection):
        f = open(self.filename, 'r', 10000)
        lines = f.readlines()
        f.close()
        input_tuples = []
        for line in lines:
            single_line = line.rstrip()
            src, tgt, w, d = single_line.split("\t", 4)
            src = "[%s" % src.split("[",1)[1]
            tgt = "[%s" % tgt.split("[",1)[1]
            input_tuples.append((eval(src), eval(tgt), float(w), float(d)))
        return _connect_from_list(input_tuples, projection)
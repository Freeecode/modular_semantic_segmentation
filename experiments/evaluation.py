"""Evaluation of trained models."""
from sacred import Experiment
from experiments.utils import ExperimentData, get_mongo_observer, load_data
from xview.datasets.synthia import AVAILABLE_SEQUENCES
from xview.models import get_model
from sys import stdout
from copy import deepcopy


def evaluate(net, data_config, print_results=True):
    """
    Evaluate the given network against the specified data and print the result.

    Args:
        net: An instance of a `base_model` class.
        data_config: A config-dict for data containing all initializer arguments and the
            dataset-name at key 'dataset'.
        print_results: If False, do not print measurements
    Returns:
        dict of measurements as produced by net.score, confusion matrix
    """
    # Load the dataset, we expect config to include the arguments
    data = load_data(data_config)
    # 'use_trainset' defaults to False if not set
    if data_config.get('use_trainset', False):
        print('INFO: Evaluating against trainset')
        batches = data.get_train_data(batch_size=1)
    else:
        batches = data.get_test_data(batch_size=1)

    measures, confusion_matrix = net.score(batches)

    if print_results:
        print('Evaluated network on {}:'.format(data_config['dataset']))
        print('total accuracy {:.2f} mean F1 {:.2f} IoU {:.2f}'.format(
            measures['total_accuracy'], measures['mean_F1'], measures['mean_IoU']))
        for label in data.labelinfo:
            print("{:>15}: {:.2f} precision, {:.2f} recall, {:.2f} IoU".format(
                data.labelinfo[label]['name'], measures['precision'][label],
                measures['recall'][label], measures['IoU'][label]))

        # There seems to be a problem with capturing the print output, flush to be sure
        stdout.flush()
    return measures, confusion_matrix


def evaluate_on_all_synthia_seqs(net, data_config):
    """
    Evaluate a network on all synthia sequences individually.
    """
    adapted_config = deepcopy(data_config)
    all_measurements = {}
    for sequence in AVAILABLE_SEQUENCES:
        adapted_config['seqs'] = [sequence]
        measurements, _ = evaluate(net, adapted_config, print_results=False)
        print('Evaluated network on {}: {:.2f} IoU'.format(sequence,
                                                           measurements['mean_IoU']))
        all_measurements[sequence] = measurements

    stdout.flush()
    return all_measurements


def import_weights_into_network(net, starting_weights, **kwargs):
    """Based on either a list of descriptions of training experiments or one description,
    load the weights produced by these trainigns into the given network.

    Args:
        net: An instance of a `base_model` inheriting class.
        starting_weights: Either dict or list of dicts.
            if dict: expect key 'experiment_id' to match a previous experiment's ID.
                if key 'filename' is not set, will search for the first artifact that
                has 'weights' in the name.
            if list: a list of dicts where each dict will be evaluated as above
        kwargs are passed to net.import_weights
    """
    def import_weights_from_description(experiment_description):
        training_experiment = ExperimentData(experiment_description['experiment_id'])
        if 'filename' not in experiment_description:
            # If no specific file specified, take first found
            filename = (artifact['name']
                        for artifact in training_experiment.get_record()['artifacts']
                        if 'weights' in artifact['name']).next()
        else:
            filename = experiment_description['filename']
        net.import_weights(training_experiment.get_artifact(filename), **kwargs)

    if isinstance(starting_weights, list):
        for experiment_description in starting_weights:
            import_weights_from_description(experiment_description)
    else:
        import_weights_from_description(starting_weights)


ex = Experiment()
ex.observers.append(get_mongo_observer())


@ex.config_hook
def load_model_configuration(config, command_name, logger):
    """
    Hook to load the model-configuration of starting-weights into the experiment info.
    """

    def get_config_for_experiment(id):
        training_experiment = ExperimentData(id)
        return training_experiment.get_record()['config']

    # This hook will produce the following update-dict for the config:
    cfg_update = {}

    if isinstance(config['starting_weights'], list):
        # For convenience, we simply record all the configurations of the trainign
        # experiments.
        cfg_update['starting_weights'] = []
        for exp_descriptor in config['starting_weights']:
            cfg_update['starting_weights'].append({'config': get_config_for_experiment(
                exp_descriptor['experiment_id'])})
    else:
        train_exp_config = get_config_for_experiment(
            config['starting_weights']['experiment_id'])
        # First, same as above, capture the information
        cfg_update['starting_weights'] = {'config': train_exp_config}
    return cfg_update


@ex.command
def also_load_config(modelname, net_config, evaluation_data, starting_weights, _run):
    """In case of only a single training experiment, we also load the exact network
    config from this experiment as a default"""
    # Load the training experiment
    training_experiment = ExperimentData(starting_weights['experiment_id'])

    model_config = training_experiment.get_record()['config']['net_config']
    model_config.update(net_config)

    # save this
    print('Running with net_config:')
    print(model_config)

    # Create the network
    model = get_model(modelname)
    with model(**model_config) as net:
        # import the weights
        import_weights_into_network(net, starting_weights)

        measurements, confusion_matrix = evaluate(net, evaluation_data)
        _run.info['measurements'] = measurements
        _run.info['confusion_matrix'] = confusion_matrix


@ex.automain
def all_synthia(modelname, net_config, evaluation_data, starting_weights, _run):
    """Load weigths from training experiments and evaluate network against specified
    data."""
    model = get_model(modelname)
    with model(**net_config) as net:
        import_weights_into_network(net, starting_weights)
        measurements = evaluate_on_all_synthia_seqs(net, evaluation_data)
        _run.info['measurements'] = measurements


@ex.automain
def main(modelname, net_config, evaluation_data, starting_weights, _run):
    """Load weigths from training experiments and evaluate network against specified
    data."""
    model = get_model(modelname)
    with model(**net_config) as net:
        import_weights_into_network(net, starting_weights)
        measurements, confusion_matrix = evaluate(net, evaluation_data)
        _run.info['measurements'] = measurements
        _run.info['confusion_matrix'] = confusion_matrix

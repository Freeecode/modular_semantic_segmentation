from sacred import Experiment
from experiments.utils import get_mongo_observer, ExperimentData
from sacred.utils import TimeoutInterrupt
from xview.datasets import get_dataset
from xview.models import get_model
from xview.settings import DATA_BASEPATH
import os


def create_directories(prefix, run_id, experiment):
    root = '/tmp/sacred/'+prefix.lower()+'_train'
    # create temporary directory for output files
    if not os.path.exists(root):
        os.makedirs(root)
    # The id of this experiment is stored in the magical _run object we get from the
    # decorator.
    output_dir = root+'/{}'.format(run_id)
    os.mkdir(output_dir)

    # Tell the experiment that this output dir is also used for tensorflow summaries
    experiment.info.setdefault("tensorflow", {}).setdefault("logdirs", [])\
        .append(output_dir)
    return output_dir


def import_startingweights(net, starting_weights):
    # load startign weights
    if starting_weights == 'washington':
        # load the washington weights
        weights = os.path.join(DATA_BASEPATH, 'darnn/FCN_weights_40000.npz')
        net.import_weights(weights, chill_mode=True)
    elif isinstance(starting_weights, dict):
        print('INFO: Loading weights from experiment {}'.format(
            starting_weights['experiment_id']))
        # load weights from previous experiment
        previous_exp = ExperimentData(starting_weights['experiment_id'])
        weights = previous_exp.get_artifact(starting_weights['filename'])
        net.import_weights(weights, chill_mode=True)
    elif isinstance(starting_weights, list):
        for weights in starting_weights:
            import_startingweights(net, weights)


ex = Experiment()
ex.observers.append(get_mongo_observer())


@ex.capture
def train_network(net, output_dir, data_config, num_iterations, starting_weights):
    # Load the dataset, we expect config to include the arguments
    dataset = get_dataset(data_config['dataset'])
    data = dataset(data_config['sequences'], data_config['batchsize'],
                   direction=data_config.get('direction', 'F'))
    # get validation set
    validation_set = data.get_validation_data(num_items=10)

    # Train the given network
    if starting_weights:
        import_startingweights(net, starting_weights)

    try:
        net.fit(data, num_iterations, validation_data=validation_set)
        timeout = False
    except KeyboardInterrupt:
        print('WARNING: Got Keyboard Interrupt, will save weights and close')
        timeout = True

    # Store the weights into the standard output directory
    net.export_weights()

    # To end the experiment, we collect all produced output files and store them.
    for filename in os.listdir(output_dir):
        ex.add_artifact(os.path.join(output_dir, filename))

    if timeout:
        raise TimeoutInterrupt


@ex.automain
def my_main(modelname, net_config, _run):
    # Set up the directories for diagnostics
    output_dir = create_directories(modelname, _run._id, ex)

    # create the network
    model = get_model(modelname)
    with model(output_dir=output_dir, **net_config) as net:
        train_network(net, output_dir)

import os
import subprocess
import argparse
import pandas as pd
import numpy as np
from matplotlib import pyplot as plt

# Output format (Berkeley):
# text    data     bss    dec     hex    filename
# 164       0       0     164      a4    libstubs.c.o (ex /home/syrmia/llvm-nanomips/llvm-test-suite-nanomips-build-1/libstubs.a)

def collectCodeSizeData(build_path, command, commandArgs) -> pd.DataFrame:

    build_abs_path = os.path.abspath(build_path)

    _, build_dir_name = os.path.split(build_abs_path)

    data = pd.DataFrame(columns=['text', 'data', 'bss', 'dec', 'hex', 'filename'])

    for root, dirs, files in os.walk(build_abs_path, followlinks=False):
        for file in files:

            # Skip object files
            file_root, file_base = os.path.split(file)
            ext = os.path.splitext(file_base)[1]
            if ext == '.o':
                continue

            # Check if file is executable
            file_processsRetVal = subprocess.run(["file", os.path.join(root, file)], capture_output=True)
            file_processsRetVal.check_returncode()
            file_output = file_processsRetVal.stdout.decode('utf-8')
            if file_output.find("executable") == -1:
                continue

            processsRetVal = subprocess.run([command] + commandArgs + [os.path.join(root, file)],
                                            capture_output=True
                                           )
            # Skip all files with unrecognized format.
            if processsRetVal.returncode == 3:
                continue

            # Raise exception if other erros occured.
            processsRetVal.check_returncode()

            # Get 'size' output as a string
            Output = processsRetVal.stdout.decode('utf-8')

            values = []
            # Process output values into list
            for i, entry in enumerate(Output.split(sep='\n')[1].split('\t')):
                # used for filename entries
                index = entry.find(build_dir_name)
                if i in range(4):
                    # 'text', 'data', 'bss', 'dec'
                    values.append(int(entry))
                elif index != -1:
                    # 'filename'
                    values.append(entry[index+len(build_dir_name):])
                else:
                    # 'hex'
                    # [or filename without build_dir_name in it,
                    # but this should not happen becuse we are taking abs path
                    # hence calling size on abs path of files]
                    values.append(entry)

            # Append new row
            data.loc[len(data),] = values

    return data

def parse_program_args(parser):
    parser.add_argument('directory_path_1', metavar='directory_path_1', action="store",
                    help="The first directory to search for executables.")
    parser.add_argument('directory_path_2', metavar='directory_path_2', action="store",
                help="The second directory to search for executables.")
    parser.add_argument('command', metavar='command', action="store",
                        help='command to run the tests')
    parser.add_argument('command_arg', metavar='command_arg', action="store", nargs='*',
                        help='command arguments')
    return parser.parse_args()

def Main():

    parser = argparse.ArgumentParser(description='Search for executables and generate code size diff.')
    args = parse_program_args(parser)

    for i in range(len(args.command_arg)):
        if not args.command_arg[i].startswith("-") and args.command_arg[i-1] != '-o':
            args.command_arg[i] = "-" + args.command_arg[i]

    print("First  build -> data1: ", args.directory_path_1)
    print("Second build -> data2: ", args.directory_path_2)
    print("command: ", args.command)
    print("command args: ", args.command_arg)

    try:
        data1 = collectCodeSizeData(args.directory_path_1, args.command, args.command_arg)
    except subprocess.CalledProcessError as e:
        print(e.returncode)
        exit()

    try:
        data2 = collectCodeSizeData(args.directory_path_2, args.command, args.command_arg)
    except subprocess.CalledProcessError as e:
        print(e.returncode)
        exit()

    print("################ Results ################")
    print("data1.shape: ", data1.shape)
    print("data2.shape: ", data2.shape)

    # 'dec' = 'text' + 'data' + 'bss'
    code_size1 = data1['dec'].sum()
    code_size2 = data2['dec'].sum()

    if code_size1 > code_size2:
        print("We have savings in code size!")
    print("Difference: ", code_size1 - code_size2)

    regression_counter = 0
    for diff in data1['dec'] - data2['dec']:
        if diff < 0:
            regression_counter = regression_counter +1
    print("We have regression in " + str(regression_counter) + " files." )
    print("###########################################")

    # Inner join data
    merged_data = pd.merge(data1, data2, on="filename", how="inner")

    # Calculate difference in size
    merged_data['diff'] = merged_data['dec_x'] - merged_data['dec_y']

    # Positive percentage means we have savings in size
    # Negative percentage means that the size is increase by that percentage
    merged_data['percentage'] = merged_data['diff'] * 100 / merged_data['dec_x']
    merged_data = merged_data.sort_values('percentage', ascending=False)

    positive_percentage_mask = np.array(list(merged_data['percentage'].astype(float))) > 0
    positive_percentage_num = positive_percentage_mask.sum()
    print("Num of percentage greater that zero: ", positive_percentage_num)

    if positive_percentage_num > 0:

        n = 20
        if positive_percentage_num < n:
            n = positive_percentage_num

        top_n_savings = merged_data.head(n)

        max_x_value = top_n_savings['dec_x'].astype(float).max()

        plt.title("Savings", fontsize=25)
        plt.barh(np.arange(n), np.array(top_n_savings['dec_x']), label="before", edgecolor='orange', color='none')
        plt.barh(np.arange(n), np.array(top_n_savings['dec_y']), label="after")
        plt.yticks(np.arange(n), np.array(top_n_savings['filename']))
        plt.xticks(np.arange(start=0, stop=int(max_x_value * 1.2), step=int(top_n_savings['dec_x'].max()*1.2) // 30), rotation=270)
        plt.ylabel("Top " + str(n) + " savings (by percentage)")
        plt.xlabel("Code size (bytes)")
        # A (dec_x, 0)
        # B (dec_x, i)
        dec_pairs = zip(list(top_n_savings['dec_x']), list(top_n_savings['dec_y']), list(top_n_savings['percentage']))
        for i, dec_pair in enumerate(dec_pairs):
            plt.text(dec_pair[0]+50, i+0.2, str(dec_pair[0]), color='orange')
            plt.text(dec_pair[0]+50, i-0.2, str(dec_pair[1]), color='blue')
            # Print "-" for positive percentage to be more intuitive, because size is decreased
            plt.text(dec_pair[0]+max_x_value*0.1, i, "-" + str(round(dec_pair[2],2)) + "%", color='orange')
        plt.legend(loc='best')
        plt.show()

    else:
        print("No saving in code size.")

    merged_data = merged_data.sort_values('percentage', ascending=True)

    negative_percentage_mask = np.array(list(merged_data['percentage'].astype(float))) < 0
    negative_percentage_num = negative_percentage_mask.sum()
    print("Num of percentage less that zero: ", negative_percentage_num)

    if negative_percentage_num > 0:

        n = 20
        if negative_percentage_num < n:
            n = negative_percentage_num

        top_n_regressions = merged_data.head(n)

        max_x_value = top_n_regressions['dec_x'].astype(float).max()

        plt.title("Regressions", fontsize=25)
        plt.barh(np.arange(n), np.array(top_n_regressions['dec_y']), label="after")
        plt.barh(np.arange(n), np.array(top_n_regressions['dec_x']), label="before", edgecolor='orange', color='none')
        plt.yticks(np.arange(n), np.array(top_n_regressions['filename']))
        plt.xticks(np.arange(start=0, stop=int(max_x_value*1.2), step=int(top_n_regressions['dec_x'].max()*1.2) // 30), rotation=270)
        plt.ylabel("Top " + str(n) + " regressions (by percentage)")
        plt.xlabel("Code size (bytes)")
        # A (dec_x, 0)
        # B (dec_x, i)
        dec_pairs = zip(list(top_n_regressions['dec_x']), list(top_n_regressions['dec_y']), list(top_n_regressions['percentage']))
        for i, dec_pair in enumerate(dec_pairs):
            plt.text(dec_pair[0]+50, i+0.2, str(dec_pair[0]), color='orange')
            plt.text(dec_pair[0]+50, i-0.2, str(dec_pair[1]), color='blue')
            # Print "+" for negative percentage to be more intuitive, because size is increased
            plt.text(dec_pair[0]+max_x_value*0.1, i, "+" + str(-1*round(dec_pair[2],2)) + "%", color='blue')
        plt.legend(loc='lower right')
        plt.show()

    else:
        print("No regressions in code size.")

if __name__ == "__main__":
  Main()